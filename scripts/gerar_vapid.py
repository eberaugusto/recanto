"""Execute localmente. NUNCA envie chaves privadas ao GitHub/chat."""
import base64
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

key=ec.generate_private_key(ec.SECP256R1())
private=key.private_bytes(serialization.Encoding.DER,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
public=key.public_key().public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint)
b64=lambda value:base64.urlsafe_b64encode(value).decode('ascii').rstrip('=')
print('COPIE PARA O RENDER > ENVIRONMENT (NUNCA PARA GITHUB):')
print('VAPID_PUBLIC_KEY='+b64(public))
print('VAPID_PRIVATE_KEY='+b64(private))
print('VAPID_SUBJECT=mailto:seu-email-de-contato@example.com')
print('Substitua o email ilustrativo pelo seu email real.')
