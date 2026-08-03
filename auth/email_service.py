import os
import secrets

def generate_verification_token():
    return secrets.token_urlsafe(32)


def send_verification_email(to_email, full_name, token):
    import resend

    api_key = os.getenv("RESEND_API_KEY")
    if not api_key:
        raise RuntimeError(
            "RESEND_API_KEY nao configurada. "
            "Adicione a chave em .env.v3 para habilitar verificacao por email."
        )
    resend.api_key = api_key

    base_url = os.getenv("APP_BASE_URL", "http://localhost:8501")
    verify_link = f"{base_url}/?verify_token={token}"

    resend.Emails.send({
        "from": os.getenv("RESEND_FROM_EMAIL", "noreply@yourdomain.com"),
        "to": to_email,
        "subject": "Confirme seu email — Assistente SIN",
        "html": f"""
        <div style="font-family: sans-serif; max-width: 480px; margin: 0 auto;">
          <h2>⚡ Assistente SIN</h2>
          <p>Ola {full_name},</p>
          <p>Confirme seu email para ativar sua conta:</p>
          <a href="{verify_link}"
             style="display:inline-block;padding:12px 24px;
             background:#F97316;color:#fff;text-decoration:none;
             border-radius:8px;">Confirmar Email</a>
          <p style="color:#888;font-size:12px;margin-top:24px;">
          Se voce nao criou esta conta, ignore este email.
          </p>
        </div>
        """
    })
