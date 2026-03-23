"""
Email Service — Sends email notifications via AWS Lambda endpoint
"""
import requests
from utils.logger import setup_logger

logger = setup_logger("EmailService")

EMAIL_API_URL = "https://wlbf2v1g1j.execute-api.ap-south-1.amazonaws.com/produce"
AUTH_TOKEN = "local-test-token"
FROM_EMAIL = "connect@igaurav.dev"
CC_EMAIL = "connect@igaurav.dev"


def send_email(to_email: str, subject: str, html_body: str, text_body: str = None):
    """
    Send email via AWS Lambda endpoint.
    
    Args:
        to_email: Recipient email address
        subject: Email subject
        html_body: HTML email body
        text_body: Plain text email body (optional)
    
    Returns:
        bool: True if email sent successfully, False otherwise
    """
    if not to_email:
        logger.warning("No recipient email provided, skipping email notification")
        return False
    
    payload = {
        "auth_token": AUTH_TOKEN,
        "mail": {
            "from": FROM_EMAIL,
            "to": [to_email],
            "cc": [CC_EMAIL],
            "subject": subject,
            "text": text_body or subject,
            "html": html_body
        }
    }
    
    try:
        logger.info(f"Sending email to {to_email}: {subject}")
        response = requests.post(EMAIL_API_URL, json=payload, timeout=10)
        
        if response.status_code == 200:
            logger.info(f"Email sent successfully to {to_email}")
            return True
        else:
            logger.error(f"Failed to send email: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        logger.error(f"Error sending email: {e}", exc_info=True)
        return False


def send_pipeline_completion_email(to_email: str, session_id: str, status: str, error_message: str = None):
    """Send email notification for pipeline completion."""
    if status == "completed":
        subject = f"✅ DFD Pipeline Completed - {session_id}"
        html_body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; padding: 20px;">
            <h2 style="color: #27ae60;">Pipeline Processing Completed</h2>
            <p>Your DFD pipeline has been successfully processed.</p>
            <p><strong>Session ID:</strong> {session_id}</p>
            <p><strong>Status:</strong> <span style="color: #27ae60;">Completed</span></p>
            <p>You can now view your results in the application.</p>
            <hr style="margin: 20px 0; border: none; border-top: 1px solid #ddd;">
            <p style="color: #666; font-size: 12px;">This is an automated notification from PIA - Privacy Impact Assessment</p>
        </body>
        </html>
        """
    else:
        subject = f"❌ DFD Pipeline Failed - {session_id}"
        html_body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; padding: 20px;">
            <h2 style="color: #e74c3c;">Pipeline Processing Failed</h2>
            <p>Unfortunately, your DFD pipeline encountered an error.</p>
            <p><strong>Session ID:</strong> {session_id}</p>
            <p><strong>Status:</strong> <span style="color: #e74c3c;">Failed</span></p>
            {f'<p><strong>Error:</strong> {error_message}</p>' if error_message else ''}
            <p>Please check the logs or contact support for assistance.</p>
            <hr style="margin: 20px 0; border: none; border-top: 1px solid #ddd;">
            <p style="color: #666; font-size: 12px;">This is an automated notification from PIA - Privacy Impact Assessment</p>
        </body>
        </html>
        """
    
    return send_email(to_email, subject, html_body)


def send_master_dfd_completion_email(to_email: str, project_id: str, status: str, total_sessions: int = 0, error_message: str = None):
    """Send email notification for master DFD completion."""
    if status == "completed":
        subject = f"✅ Master DFD Completed - {project_id}"
        html_body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; padding: 20px;">
            <h2 style="color: #27ae60;">Master DFD Generation Completed</h2>
            <p>Your master DFD has been successfully generated from {total_sessions} sessions.</p>
            <p><strong>Project ID:</strong> {project_id}</p>
            <p><strong>Status:</strong> <span style="color: #27ae60;">Completed</span></p>
            <p><strong>Sessions Aggregated:</strong> {total_sessions}</p>
            <p>You can now view your master DFD in the application.</p>
            <hr style="margin: 20px 0; border: none; border-top: 1px solid #ddd;">
            <p style="color: #666; font-size: 12px;">This is an automated notification from PIA - Privacy Impact Assessment</p>
        </body>
        </html>
        """
    else:
        subject = f"❌ Master DFD Failed - {project_id}"
        html_body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; padding: 20px;">
            <h2 style="color: #e74c3c;">Master DFD Generation Failed</h2>
            <p>Unfortunately, your master DFD generation encountered an error.</p>
            <p><strong>Project ID:</strong> {project_id}</p>
            <p><strong>Status:</strong> <span style="color: #e74c3c;">Failed</span></p>
            {f'<p><strong>Error:</strong> {error_message}</p>' if error_message else ''}
            <p>Please check the logs or contact support for assistance.</p>
            <hr style="margin: 20px 0; border: none; border-top: 1px solid #ddd;">
            <p style="color: #666; font-size: 12px;">This is an automated notification from PIA - Privacy Impact Assessment</p>
        </body>
        </html>
        """
    
    return send_email(to_email, subject, html_body)
