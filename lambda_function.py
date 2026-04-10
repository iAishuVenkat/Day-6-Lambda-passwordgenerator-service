import json
import os
import secrets
import string
import boto3
from botocore.exceptions import ClientError

# Initialize KMS client
kms = boto3.client('kms')

SYMBOLS = "!@#$%^&*()_+-=[]{}|;:,.?"
ALPHABETS = string.ascii_letters
NUMERICALS = string.digits

MIN_LENGTH = 8
MAX_LENGTH = 10
DEFAULT_LENGTH = 10

# Cache for decrypted values
_decrypted_cache = {}


def decrypt_env_var(env_var_name):
    """Decrypt KMS-encrypted environment variable"""
    if env_var_name in _decrypted_cache:
        return _decrypted_cache[env_var_name]
    
    encrypted_value = os.environ.get(env_var_name)
    if not encrypted_value:
        return None
    
    try:
        # Try to decrypt - if it fails, assume it's plaintext
        response = kms.decrypt(CiphertextBlob=encrypted_value.encode())
        decrypted_value = response['Plaintext'].decode()
        _decrypted_cache[env_var_name] = decrypted_value
        return decrypted_value
    except ClientError:
        # If decryption fails, treat as plaintext (for backward compatibility)
        _decrypted_cache[env_var_name] = encrypted_value
        return encrypted_value


def error_response(status_code, code, message):
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"error": {"code": code, "message": message}})
    }


def success_response(passcode, length, options):
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({
            "passcode": passcode,
            "length": length,
            "options": options
        })
    }


def lambda_handler(event, context):
    try:
        # Method check
        http_method = event.get("httpMethod", "GET")
        if http_method != "GET":
            return error_response(405, "METHOD_NOT_ALLOWED", "Only GET requests are supported")

        # API key authentication - decrypt if needed
        headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
        api_key = headers.get("x-api-key")
        expected_key = decrypt_env_var("API_SECRET_KEY")

        if not api_key or api_key != expected_key:
            return error_response(401, "UNAUTHORIZED", "Missing or invalid API key")

        # Parse query parameters
        params = event.get("queryStringParameters") or {}

        # Validate and parse length
        raw_length = params.get("length", str(DEFAULT_LENGTH))
        try:
            length = int(raw_length)
        except ValueError:
            return error_response(400, "INVALID_LENGTH", "Length must be an integer between 8 and 10")

        if length < MIN_LENGTH or length > MAX_LENGTH:
            return error_response(400, "INVALID_LENGTH", "Length must be an integer between 8 and 10")

        # Validate boolean params
        def parse_bool(value, param_name):
            if value is None:
                return True, None  # default true
            if value.lower() == "true":
                return True, None
            if value.lower() == "false":
                return False, None
            return None, param_name

        symbols_val, err = parse_bool(params.get("symbols"), "symbols")
        if err:
            return error_response(400, "INVALID_PARAM", f"Invalid value for parameter '{err}'")

        alphabets_val, err = parse_bool(params.get("alphabets"), "alphabets")
        if err:
            return error_response(400, "INVALID_PARAM", f"Invalid value for parameter '{err}'")

        numericals_val, err = parse_bool(params.get("numericals"), "numericals")
        if err:
            return error_response(400, "INVALID_PARAM", f"Invalid value for parameter '{err}'")

        # All three must be true
        if not symbols_val or not alphabets_val or not numericals_val:
            return error_response(400, "NO_CHARSET", "symbols, alphabets, and numericals must all be true")

        # Build charset and generate passcode
        charset = SYMBOLS + ALPHABETS + NUMERICALS
        passcode = "".join(secrets.choice(charset) for _ in range(length))

        options = {
            "symbols": symbols_val,
            "alphabets": alphabets_val,
            "numericals": numericals_val
        }

        return success_response(passcode, length, options)

    except Exception as e:
        print(f"Unexpected error: {str(e)}")  # This will go to CloudWatch logs
        return error_response(500, "INTERNAL_ERROR", "An unexpected error occurred")