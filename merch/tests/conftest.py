import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_tmp = tempfile.mkdtemp(prefix="merch-test-")
os.environ.setdefault("MERCH_DATA_DIR", _tmp)
os.environ.setdefault("MERCH_PRODUCTION_PIN", "2222")
os.environ.setdefault("MERCH_ADMIN_PIN", "9999")
os.environ.setdefault("MERCH_SERIAL_KEY", "0123456789abcdef0123456789abcdef")
# тесты ходят по http://testserver — Secure-cookie при https-адресе не вернулись бы
os.environ.setdefault("MERCH_PUBLIC_URL", "http://testserver")
os.environ.setdefault("MERCH_VERIFY_PER_MIN", "1000")
os.environ.setdefault("MERCH_REGISTER_PER_MIN", "1000")
os.environ.setdefault("MERCH_ISSUE_PER_MIN", "1000")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-client-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("MERCH_ADMIN_EMAILS", "boss@example.com")
