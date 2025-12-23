import smtplib
import boto3
import os
import json
from datetime import datetime
from email.message import EmailMessage

# SMTP Configuration
SMTP_SERVER = "smtp-mail.outlook.com"  # Replace with your SMTP server
SMTP_PORT = 587  # Use 465 for SSL or 587 for TLS
SMTP_USER = "xxxx@xxxxxxx.com"  # Replace with your email
SMTP_PASS = "xxxxxx"  # Store securely, avoid hardcoding

# List of recipients
TO_EMAILS = ["infra@xxxxx.com","securitymonitoring@xxxxx.com","vapt@xxxxx.com"]  # Replace with recipient emails

# S3 Configuration
S3_BUCKET = "opl-inventory-details"

def get_s3_file_key():
    """Generate the correct file name based on the date."""
    date_str = datetime.now().strftime("%d-%m-%Y")
    return f"{date_str}/aws_inventory_opl_{date_str}.xlsx"

def download_from_s3(file_key):
    """Download the file from S3 to Lambda's /tmp/ directory."""
    local_path = f"/tmp/{os.path.basename(file_key)}"
    try:
        boto3.client("s3").download_file(S3_BUCKET, file_key, local_path)
        print(f"Downloaded {file_key} from S3 to {local_path}")
        return local_path
    except Exception as e:
        print(f"Error downloading file from S3: {e}")
        raise

def send_email_with_attachment(file_path):
    """Send an email with the S3 file as an attachment."""
    msg = EmailMessage()
    msg["Subject"] = f"OPL - AWS Resource Inventory Report -{datetime.now().strftime('%d-%m-%Y')}"
    msg["From"] = SMTP_USER
    msg["To"] = ", ".join(TO_EMAILS)

    email_body = """
    Hello Sir/Madam,
    
    Please find attached the latest OPL - AWS Resource Inventory Report.
    
    Regards,
    Infra Team
    """
    msg.set_content(email_body.strip())

    # Attach the file
    with open(file_path, "rb") as f:
        msg.add_attachment(f.read(), maintype="application", subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet", filename=os.path.basename(file_path))

    # Send email
    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()  # Secure connection
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)
        print("Email sent successfully")

def lambda_handler(event, context):
    """AWS Lambda entry point."""
    try:
        s3_file_key = get_s3_file_key()
        file_path = download_from_s3(s3_file_key)
        send_email_with_attachment(file_path)

        return {
            "statusCode": 200,
            "body": json.dumps("Email sent successfully!")
        }
    except Exception as e:
        print(f"Error: {str(e)}")
        return {
            "statusCode": 500,
            "body": json.dumps(f"Error: {str(e)}")
        }
