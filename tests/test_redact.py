"""Redaksiyon: gercek sirlar maskelenmeli, pentest ciktisi DOKUNULMADAN gecmeli.

Ikinci kisim en az birincisi kadar onemli. Bir sir sizarsa kotu; ama nmap
port listesi ya da NTLM hash'i maskelenirse arac isini yapamaz hale gelir -
mentorun bakmasi gereken sey tam olarak odur.
"""

from __future__ import annotations

import unittest

from alleye import redact


def clean(text: str) -> str:
    return redact.redact(text)[0]


def hits(text: str) -> list[str]:
    return redact.redact(text)[1]


class TestSecretsMasked(unittest.TestCase):
    """Bunlarin hicbiri buluta cikmamali."""

    def assert_masked(self, text: str, secret: str, rule: str) -> None:
        out, fired = redact.redact(text)
        self.assertNotIn(secret, out, f"{rule}: sir maskelenmemis -> {out!r}")
        self.assertIn(rule, fired, f"{rule} kurali tetiklenmedi -> {fired}")

    def test_gemini_auth_key(self):
        # Yeni Google "auth key" formati. Projenin kendi anahtari bu formatta.
        self.assert_masked(
            "GEMINI_API_KEY=AQ.Ab8RN6JmXk2pQwErTyUiOpAsDfGhJkLzXcVbNm",
            "AQ.Ab8RN6JmXk2pQwErTyUiOpAsDfGhJkLzXcVbNm", "google-authkey")

    def test_gemini_legacy_key(self):
        self.assert_masked(
            "curl -H 'x-goog-api-key: AIzaSyB1234567890abcdefghijklmnopqrstuvw'",
            "AIzaSyB1234567890abcdefghijklmnopqrstuvw", "google-key")

    def test_groq_key(self):
        self.assert_masked("GROQ_API_KEY=gsk_abcdefghij0123456789KLMNOPQRSTUV",
                           "gsk_abcdefghij0123456789KLMNOPQRSTUV", "groq-key")

    def test_openai_key(self):
        self.assert_masked("export OPENAI=sk-proj-abcdefghijklmnopqrstuvwxyz012345",
                           "sk-proj-abcdefghijklmnopqrstuvwxyz012345", "openai-key")

    def test_github_token(self):
        self.assert_masked("git remote set-url origin https://ghp_ABCdef0123456789ABCdef0123456789ABCD@github.com/x/y",
                           "ghp_ABCdef0123456789ABCdef0123456789ABCD", "github-token")

    def test_slack_token(self):
        self.assert_masked("SLACK=xoxb-1234567890-ABCdefGHIjkl",
                           "xoxb-1234567890-ABCdefGHIjkl", "slack-token")

    def test_huggingface_token(self):
        self.assert_masked("hf_ABCdefGHIjklMNOpqrSTUvwxYZ0123456789",
                           "hf_ABCdefGHIjklMNOpqrSTUvwxYZ0123456789", "hf-token")

    def test_aws_key_id(self):
        self.assert_masked("aws_access_key_id = AKIAIOSFODNN7EXAMPLE",
                           "AKIAIOSFODNN7EXAMPLE", "aws-key-id")

    def test_jwt(self):
        jwt = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
               ".eyJzdWIiOiIxMjM0NTY3ODkwIn0"
               ".dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U")
        self.assert_masked(f"Cookie: session={jwt}", jwt, "jwt")

    def test_bearer_header(self):
        out, fired = redact.redact("Authorization: Bearer abcdefghij1234567890XYZ")
        self.assertNotIn("abcdefghij1234567890XYZ", out)
        self.assertIn("bearer", fired)
        # Basligin kendisi kalmali - modelin ne oldugunu anlamasi gerekiyor.
        self.assertIn("Bearer", out)

    def test_private_key_block(self):
        pem = ("-----BEGIN RSA PRIVATE KEY-----\n"
               "MIIEpAIBAAKCAQEA1234567890abcdefghij\n"
               "kLmNoPqRsTuVwXyZ0987654321\n"
               "-----END RSA PRIVATE KEY-----")
        out, fired = redact.redact(f"cat id_rsa\n{pem}\n")
        self.assertNotIn("MIIEpAIBAAKCAQEA", out)
        self.assertNotIn("BEGIN RSA PRIVATE KEY", out)
        self.assertIn("private-key", fired)

    def test_env_style_secret(self):
        out, fired = redact.redact("DB_PASSWORD=SuperGizli123\nAPP_SECRET: cokgizli\n")
        self.assertNotIn("SuperGizli123", out)
        self.assertNotIn("cokgizli", out)
        self.assertIn("env-secret", fired)
        # Anahtarin ADI kalmali: hangi degiskenin sir oldugu bilgi degeri tasiyor.
        self.assertIn("DB_PASSWORD", out)

    def test_cli_password_flag(self):
        out, _ = redact.redact("ssh-copy-id --password Hunter2! user@10.10.11.42")
        self.assertNotIn("Hunter2!", out)
        # Hedef IP ve kullanici DURMALI.
        self.assertIn("10.10.11.42", out)

    def test_tool_short_password_flag(self):
        out, fired = redact.redact("mysql -u root -pHunter2 -h 10.10.11.42")
        self.assertNotIn("Hunter2", out)
        self.assertIn("tool-password", fired)
        self.assertIn("10.10.11.42", out)

    def test_smb_user_percent_password(self):
        out, fired = redact.redact("smbclient -L //10.10.11.42 -U administrator%Winter2026!")
        self.assertNotIn("Winter2026!", out)
        self.assertIn("smb-userpass", fired)
        # Kullanici adi pentest'te bilgi - maskelenmemeli.
        self.assertIn("administrator", out)

    def test_connection_string(self):
        out, fired = redact.redact("postgres://alleye:s3cr3tpw@db.local:5432/alleye")
        self.assertNotIn("s3cr3tpw", out)
        self.assertIn("conn-string", fired)
        self.assertIn("db.local:5432", out)


NMAP_OUTPUT = """$ nmap -p- -sV -T4 10.10.11.42
Nmap scan report for forest.htb (10.10.11.42)
PORT      STATE SERVICE       VERSION
22/tcp    open  ssh           OpenSSH 8.2p1 Ubuntu 4ubuntu0.5
88/tcp    open  kerberos-sec  Microsoft Windows Kerberos
445/tcp   open  microsoft-ds  Windows Server 2019 Standard 17763
5985/tcp  open  http          Microsoft HTTPAPI httpd 2.0
$ nmap -p80,443,8080 --open 10.10.11.42
$ gobuster dir -u http://10.10.11.42:8080 -w common.txt
[+] /admin (Status: 200) [Size: 1234]
"""

NTLM_DUMP = """Administrator:500:aad3b435b51404eeaad3b435b51404ee:32ed87bdb5fdc5e9cba88547376818d4:::
Guest:501:aad3b435b51404eeaad3b435b51404ee:31d6cfe0d16ae931b73c59d7e0c089c0:::
svc_backup:1103:aad3b435b51404eeaad3b435b51404ee:9658d1d1dcd9250115e2205d9f48400d:::
"""


class TestPentestOutputUntouched(unittest.TestCase):
    """Bu blok bilincli bir tasarim karari: pentest mentoru bunlara BAKMALI."""

    def test_nmap_port_flags_survive(self):
        out, fired = redact.redact(NMAP_OUTPUT)
        # "-p-" ve "-p80,443" kisa parola bayragi sanilip silinmemeli.
        self.assertIn("-p-", out)
        self.assertIn("-p80,443,8080", out)
        self.assertEqual(out, NMAP_OUTPUT, f"nmap ciktisi degistirildi, kurallar: {fired}")
        self.assertEqual(fired, [])

    def test_ports_services_versions_survive(self):
        out = clean(NMAP_OUTPUT)
        for token in ("22/tcp", "5985/tcp", "OpenSSH 8.2p1", "Windows Server 2019",
                      "10.10.11.42", "forest.htb", "http://10.10.11.42:8080"):
            self.assertIn(token, out)

    def test_ntlm_hashes_survive(self):
        out, fired = redact.redact(NTLM_DUMP)
        self.assertEqual(out, NTLM_DUMP, f"NTLM dump degistirildi, kurallar: {fired}")
        self.assertIn("32ed87bdb5fdc5e9cba88547376818d4", out)
        self.assertIn("aad3b435b51404eeaad3b435b51404ee", out)

    def test_usernames_and_rids_survive(self):
        out = clean(NTLM_DUMP)
        self.assertIn("Administrator:500", out)
        self.assertIn("svc_backup:1103", out)

    def test_hydra_style_target_survives(self):
        # Kullanici adi ve hedef kalir; sadece wordlist yolu gibi seyler degil.
        text = "hydra -l administrator -P rockyou.txt 10.10.11.42 smb"
        self.assertEqual(clean(text), text)


class TestBehaviour(unittest.TestCase):
    def test_empty_input(self):
        self.assertEqual(redact.redact(""), ("", []))

    def test_no_secret_no_change(self):
        text = "git status\nOn branch main\nnothing to commit"
        self.assertEqual(redact.redact(text), (text, []))

    def test_redact_if_disabled_passes_through(self):
        secret = "GEMINI_API_KEY=AQ.Ab8RN6JmXk2pQwErTyUiOpAsDfGhJkLz"
        self.assertEqual(redact.redact_if(False, secret), (secret, []))
        self.assertNotEqual(redact.redact_if(True, secret)[0], secret)

    def test_multiple_rules_report_each_once(self):
        text = ("A_TOKEN=abc123\nB_SECRET=def456\n"
                "key=AQ.Ab8RN6JmXk2pQwErTyUiOpAsDfGhJkLz\n")
        fired = hits(text)
        self.assertEqual(len(fired), len(set(fired)), "ayni kural iki kez raporlanmis")
        self.assertIn("env-secret", fired)
        self.assertIn("google-authkey", fired)


if __name__ == "__main__":
    unittest.main()
