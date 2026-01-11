import os
import hmac
import subprocess
import logging
import signal
import re
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
from datetime import datetime, timezone

CONTENT_TYPE_JSON = 'application/json'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

DEPLOY_WEBHOOK_SECRET = os.getenv('DEPLOY_WEBHOOK_SECRET', '')
PORT = int(os.getenv('PORT', '9000'))
COMMAND_TIMEOUT = int(os.getenv('COMMAND_TIMEOUT', '600'))

if not DEPLOY_WEBHOOK_SECRET:
    raise ValueError("DEPLOY_WEBHOOK_SECRET environment variable is required")

ALLOWED_COMMANDS = [
    r'^cd\s+',
    r'^git\s+',
    r'^docker\s+',
]

BLOCKED_PATTERNS = [
    r'\brm\s+-rf',
    r'\brm\s+-r\s+',
    r'\brm\s+',
    r'\bdelete\s+',
    r'\bformat\s+',
    r'\bdd\s+',
    r'\bmkfs\s+',
    r'\b>.*/dev/',
    r'\|\s*sh\s*$',
    r'\|\s*bash\s*$',
    r';\s*rm\s+',
    r'&&\s*rm\s+',
    r'\|\s*rm\s+',
]

class DeploymentHandler(BaseHTTPRequestHandler):
    def log_message(self, format_str, *args):
        client_ip = self.client_address[0]
        try:
            if args:
                message = format_str % args
            else:
                message = format_str
            logger.info(f"{client_ip} - {message}")
        except (TypeError, ValueError):
            logger.info(f"{client_ip} - {format_str}")

    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-Type', CONTENT_TYPE_JSON)
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'healthy', 'timestamp': datetime.now(timezone.utc).isoformat()}).encode())
            return
        
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        if self.path == '/deploy':
            self.handle_deploy()
        else:
            self.send_response(404)
            self.end_headers()

    def handle_deploy(self):
        client_ip = self.client_address[0]
        
        auth_header = self.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            logger.warning(f"{client_ip} - Missing or invalid Authorization header")
            self.send_response(401)
            self.send_header('Content-Type', CONTENT_TYPE_JSON)
            self.end_headers()
            self.wfile.write(json.dumps({'error': 'Unauthorized'}).encode())
            return
        
        token = auth_header[7:]
        
        if not self.validate_token(token):
            logger.warning(f"{client_ip} - Invalid token")
            self.send_response(401)
            self.send_header('Content-Type', CONTENT_TYPE_JSON)
            self.end_headers()
            self.wfile.write(json.dumps({'error': 'Invalid token'}).encode())
            return
        
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            payload = json.loads(body.decode('utf-8')) if content_length > 0 else {}
            commit = payload.get('commit', 'unknown')
            command = payload.get('command', '')
            
            if not command:
                logger.warning(f"{client_ip} - Missing command in request")
                self.send_response(400)
                self.send_header('Content-Type', CONTENT_TYPE_JSON)
                self.end_headers()
                self.wfile.write(json.dumps({'error': 'Missing command in request'}).encode())
                return
            
            validation_result = self.validate_command(command)
            if not validation_result['valid']:
                logger.warning(f"{client_ip} - Invalid command rejected: {validation_result['reason']}")
                self.send_response(400)
                self.send_header('Content-Type', CONTENT_TYPE_JSON)
                self.end_headers()
                self.wfile.write(json.dumps({
                    'error': 'Invalid command',
                    'reason': validation_result['reason']
                }).encode())
                return
            
            logger.info(f"{client_ip} - Deployment request received for commit: {commit}, command: {command[:100]}")
            
            result = self.execute_deployment(commit, command)
            
            if result['success']:
                self.send_response(200)
                self.send_header('Content-Type', CONTENT_TYPE_JSON)
                self.end_headers()
                self.wfile.write(json.dumps({
                    'status': 'success',
                    'message': 'Deployment completed',
                    'commit': commit,
                    'output': result.get('output', '')
                }).encode())
                logger.info(f"{client_ip} - Deployment successful for commit: {commit}")
            else:
                self.send_response(500)
                self.send_header('Content-Type', CONTENT_TYPE_JSON)
                self.end_headers()
                self.wfile.write(json.dumps({
                    'status': 'error',
                    'message': 'Deployment failed',
                    'commit': commit,
                    'error': result.get('error', '')
                }).encode())
                logger.error(f"{client_ip} - Deployment failed for commit: {commit}: {result.get('error', '')}")
        
        except json.JSONDecodeError:
            logger.error(f"{client_ip} - Invalid JSON payload")
            self.send_response(400)
            self.send_header('Content-Type', CONTENT_TYPE_JSON)
            self.end_headers()
            self.wfile.write(json.dumps({'error': 'Invalid JSON'}).encode())
        except Exception as e:
            logger.error(f"{client_ip} - Unexpected error: {str(e)}")
            self.send_response(500)
            self.send_header('Content-Type', CONTENT_TYPE_JSON)
            self.end_headers()
            self.wfile.write(json.dumps({'error': 'Internal server error'}).encode())

    def validate_token(self, token):
        expected_token = DEPLOY_WEBHOOK_SECRET
        return hmac.compare_digest(token, expected_token)

    def validate_command(self, command):
        command = command.strip()
        
        if not command:
            return {'valid': False, 'reason': 'Empty command'}
        
        for pattern in BLOCKED_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                return {'valid': False, 'reason': f'Blocked dangerous pattern: {pattern}'}
        
        commands = re.split(r'\s*&&\s*|\s*;\s*', command)
        has_allowed = False
        
        for cmd in commands:
            cmd = cmd.strip()
            if not cmd:
                continue
            
            is_allowed = False
            for allowed_pattern in ALLOWED_COMMANDS:
                if re.match(allowed_pattern, cmd, re.IGNORECASE):
                    is_allowed = True
                    has_allowed = True
                    break
            
            if not is_allowed:
                return {'valid': False, 'reason': f'Command not in whitelist: {cmd[:50]}'}
        
        if not has_allowed:
            return {'valid': False, 'reason': 'No allowed commands found'}
        
        return {'valid': True}

    def execute_deployment(self, commit, command):
        logger.info(f"Starting deployment for commit: {commit}")
        try:
            result = self.run_deploy_command(command)
            if result['success']:
                logger.info(f"Deployment completed successfully for commit: {commit}")
            return result
        
        except Exception as e:
            logger.error(f"Deployment error for commit {commit}: {str(e)}")
            return {'success': False, 'error': str(e)}

    def run_deploy_command(self, command):
        try:
            logger.info(f"Executing command: {command}")
            
            process = subprocess.Popen(
                command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                preexec_fn=os.setsid
            )
            
            try:
                stdout, stderr = process.communicate(timeout=COMMAND_TIMEOUT)
                if process.returncode == 0:
                    output = stdout.decode('utf-8', errors='ignore')
                    logger.info(f"Deployment command successful: {output[:200]}")
                    return {'success': True, 'output': output}
                else:
                    error = stderr.decode('utf-8', errors='ignore')
                    logger.error(f"Deployment command failed: {error}")
                    return {'success': False, 'error': f'Deployment failed: {error}'}
            except subprocess.TimeoutExpired:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                logger.error(f"Deployment command timed out after {COMMAND_TIMEOUT} seconds")
                return {'success': False, 'error': f'Deployment timed out after {COMMAND_TIMEOUT} seconds'}
        
        except Exception as e:
            logger.error(f"Error running deployment command: {str(e)}")
            return {'success': False, 'error': f'Deployment error: {str(e)}'}

def main():
    logger.info(f"Starting deployment webhook service on port {PORT}")
    logger.info(f"COMMAND_TIMEOUT: {COMMAND_TIMEOUT}s")
    logger.info("Commands accepted from request payload (include cd for directory changes)")
    
    server = HTTPServer(('0.0.0.0', PORT), DeploymentHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down server...")
        server.shutdown()

if __name__ == '__main__':
    main()
