import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

SMTP_HOST = os.getenv('SMTP_HOST', 'smtp-alt.services.cityoffargo.com')
SMTP_PORT = int(os.getenv('SMTP_PORT', '25'))
SMTP_FROM = os.getenv('SMTP_FROM', 'NoReply@FargoND.gov')
QUARTERMASTER_EMAIL = os.getenv('QUARTERMASTER_EMAIL', '')

SMTP_USER = os.getenv('SMTP_USER', '')
SMTP_PASS = os.getenv('SMTP_PASS', '')

def send_email(to_email, subject, html_body, text_body=None):
    """Send an email via SMTP. Logs failures to console."""
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = SMTP_FROM
        msg['To'] = to_email
        
        if text_body:
            msg.attach(MIMEText(text_body, 'plain'))
        msg.attach(MIMEText(html_body, 'html'))
        
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            if SMTP_PORT == 587:
                server.ehlo()
                server.starttls()
                server.ehlo()
            if SMTP_USER and SMTP_PASS:
                server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_FROM, to_email, msg.as_string())
        
        print(f"Email sent to {to_email}: {subject}")
        return True
        
    except Exception as e:
        print(f"Email failed to {to_email}: {e}")
        return False

def send_inspection_assignment(assigned_to_email, assigned_by, vehicle_name, inspection_type, due_date, fob_id):
    """Email sent to supervisor when assigned an inspection."""
    type_label = "Monthly Cleanliness Check" if inspection_type == "cleanliness" else "Quarterly Inventory"
    inspect_url = f"https://pd-checkout.cityoffargo.com/inspect/{fob_id}"
    
    subject = f"Vehicle Inspection Assignment: {vehicle_name}"
    html = f"""
    <h2>Vehicle Inspection Assignment</h2>
    <p>You have been assigned a <strong>{type_label}</strong> for <strong>{vehicle_name}</strong>.</p>
    <table style="border-collapse: collapse; margin: 15px 0;">
        <tr><td style="padding: 5px 15px 5px 0;"><strong>Vehicle:</strong></td><td>{vehicle_name}</td></tr>
        <tr><td style="padding: 5px 15px 5px 0;"><strong>Type:</strong></td><td>{type_label}</td></tr>
        <tr><td style="padding: 5px 15px 5px 0;"><strong>Assigned By:</strong></td><td>{assigned_by}</td></tr>
        <tr><td style="padding: 5px 15px 5px 0;"><strong>Due Date:</strong></td><td>{due_date}</td></tr>
    </table>
    <p><a href="{inspect_url}" style="background: #2196F3; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">Complete Inspection</a></p>
    <p style="color: #666; font-size: 12px;">Fargo Police Department Checkout System</p>
    """
    return send_email(assigned_to_email, subject, html)

def send_inspection_reminder(assigned_to_email, vehicle_name, inspection_type, due_date, fob_id):
    """Reminder email sent 7 days before due date."""
    type_label = "Monthly Cleanliness Check" if inspection_type == "cleanliness" else "Quarterly Inventory"
    inspect_url = f"https://pd-checkout.cityoffargo.com/inspect/{fob_id}"
    
    subject = f"Reminder: Vehicle Inspection Due - {vehicle_name}"
    html = f"""
    <h2>Inspection Reminder</h2>
    <p>This is a reminder that your <strong>{type_label}</strong> for <strong>{vehicle_name}</strong> is due on <strong>{due_date}</strong>.</p>
    <p><a href="{inspect_url}" style="background: #FF9800; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">Complete Inspection Now</a></p>
    <p style="color: #666; font-size: 12px;">Fargo Police Department Checkout System</p>
    """
    return send_email(assigned_to_email, subject, html)

def send_inspection_issues_to_quartermaster(vehicle_name, inspection_type, inspector, inspected_at, issues, comments, fob_id, inspection_id):
    """Email quartermaster when an inspection has issues."""
    if not QUARTERMASTER_EMAIL:
        print("QUARTERMASTER_EMAIL not set, skipping notification")
        return False
    
    type_label = "Monthly Cleanliness Check" if inspection_type == "cleanliness" else "Quarterly Inventory"
    detail_url = f"https://pd-checkout.cityoffargo.com/admin/inspection/{inspection_type}/{inspection_id}"
    
    subject = f"Inspection Issues Found: {vehicle_name}"
    
    issues_html = "".join([f"<li style=\"color: red;\">{issue}</li>" for issue in issues])
    
    html = f"""
    <h2>Vehicle Inspection - Issues Found</h2>
    <p>An inspection was completed with issues that require attention.</p>
    <table style="border-collapse: collapse; margin: 15px 0;">
        <tr><td style="padding: 5px 15px 5px 0;"><strong>Vehicle:</strong></td><td>{vehicle_name}</td></tr>
        <tr><td style="padding: 5px 15px 5px 0;"><strong>Type:</strong></td><td>{type_label}</td></tr>
        <tr><td style="padding: 5px 15px 5px 0;"><strong>Inspector:</strong></td><td>{inspector}</td></tr>
        <tr><td style="padding: 5px 15px 5px 0;"><strong>Completed:</strong></td><td>{inspected_at}</td></tr>
    </table>
    <h3 style="color: red;">Issues Found:</h3>
    <ul>{issues_html}</ul>
    {"<p><strong>Comments:</strong> " + comments + "</p>" if comments else ""}
    <p><a href="{detail_url}" style="background: #f44336; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">View Full Inspection</a></p>
    <p style="color: #666; font-size: 12px;">Fargo Police Department Checkout System</p>
    """
    return send_email(QUARTERMASTER_EMAIL, subject, html)
