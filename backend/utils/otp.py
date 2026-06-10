import random
import string

def generate_numeric_otp(length: int = 6) -> str:
    """Generate a cryptographically safe numeric OTP."""
    return ''.join(random.SystemRandom().choices(string.digits, k=length))
