"""Email delivery service using standard Python smtplib with Gmail TLS (Port 587).

Sends styled HTML OTP verification emails for user registration and password reset.
If mail credentials are not configured, logs the OTP to console/logger so development works offline.
"""

from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from src.config import get_settings

logger = logging.getLogger(__name__)


def send_otp_email(to_email: str, otp_code: str, purpose: str = "register") -> None:
    """Send an OTP code email to the specified recipient via Gmail SMTP.

    :param to_email: Target recipient email.
    :param otp_code: 6-digit OTP code string.
    :param purpose: Context ("register" or "forgot_password").
    """
    settings = get_settings()

    purpose_title = "Xác thực Đăng ký Tài khoản" if purpose == "register" else "Khôi phục Mật khẩu"
    purpose_desc = (
        "Cảm ơn bạn đã đăng ký tài khoản SceneSearch! Vui lòng dùng mã OTP bên dưới để hoàn tất đăng ký."
        if purpose == "register"
        else "Chúng tôi đã nhận được yêu cầu đặt lại mật khẩu cho tài khoản của bạn."
    )

    subject = f"[SceneSearch] Mã OTP {purpose_title}: {otp_code}"

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8">
      <style>
        body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #0f172a; color: #f8fafc; margin: 0; padding: 20px; }}
        .container {{ max-width: 520px; margin: 0 auto; background: #1e293b; border-radius: 16px; border: 1px solid #334155; padding: 32px; box-shadow: 0 10px 25px rgba(0,0,0,0.5); }}
        .header {{ text-align: center; border-bottom: 1px solid #334155; padding-bottom: 20px; margin-bottom: 24px; }}
        .brand {{ color: #a855f7; font-size: 22px; font-weight: 700; letter-spacing: -0.5px; }}
        .title {{ color: #f8fafc; font-size: 18px; font-weight: 600; margin-top: 8px; }}
        .body-text {{ color: #94a3b8; font-size: 14px; line-height: 1.6; margin-bottom: 24px; }}
        .otp-box {{ background: #090d16; border: 1px dashed #8b5cf6; border-radius: 12px; padding: 20px; text-align: center; margin: 24px 0; }}
        .otp-code {{ font-size: 32px; font-weight: 800; letter-spacing: 8px; color: #c084fc; font-family: monospace; }}
        .warning {{ font-size: 13px; color: #ef4444; background: rgba(239, 68, 68, 0.1); border-left: 3px solid #ef4444; padding: 10px 14px; border-radius: 4px; margin-top: 20px; }}
        .footer {{ font-size: 12px; color: #64748b; text-align: center; margin-top: 32px; border-top: 1px solid #334155; padding-top: 16px; }}
      </style>
    </head>
    <body>
      <div class="container">
        <div class="header">
          <div class="brand">SSP · SceneSearch AI</div>
          <div class="title">{purpose_title}</div>
        </div>
        <div class="body-text">
          Xin chào,<br><br>
          {purpose_desc}
        </div>
        <div class="otp-box">
          <div style="font-size: 12px; color: #94a3b8; margin-bottom: 8px; text-transform: uppercase;">Mã xác thực OTP của bạn</div>
          <div class="otp-code">{otp_code}</div>
        </div>
        <div class="warning">
          ⏰ <strong>Mã OTP này có hiệu lực trong vòng 5 phút.</strong> Vui lòng không chia sẻ mã này cho bất kỳ ai.
        </div>
        <div class="footer">
          © 2026 SceneSearch AI Project. Email tự động, vui lòng không phản hồi email này.
        </div>
      </div>
    </body>
    </html>
    """

    if not settings.mail_username or not settings.mail_password:
        logger.warning(
            "SMTP Mail credentials missing in .env! (MAIL_USERNAME/MAIL_PASSWORD). OTP code for %s (%s) is: %s",
            to_email,
            purpose,
            otp_code,
        )
        return

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = settings.mail_username
        msg["To"] = to_email

        part = MIMEText(html_content, "html", "utf-8")
        msg.attach(part)

        clean_password = settings.mail_password.replace(" ", "").strip()

        server = smtplib.SMTP(settings.mail_host, settings.mail_port, timeout=10)
        server.starttls()
        server.login(settings.mail_username, clean_password)
        server.sendmail(settings.mail_username, [to_email], msg.as_string())
        server.quit()
        logger.info("Sent OTP email successfully to %s (purpose=%s)", to_email, purpose)
    except Exception as exc:
        logger.error("Failed to send OTP email to %s via SMTP: %s", to_email, exc)
        raise ValueError(f"Không thể gửi email OTP đến {to_email}. Chi tiết lỗi từ Gmail: {exc}") from exc
