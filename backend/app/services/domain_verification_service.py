"""
Domain verification service for validating website ownership via DNS.
"""
import logging
import dns.resolver
from typing import Optional, Dict
from datetime import datetime, timezone
from app.config import settings

logger = logging.getLogger(__name__)


class DomainVerificationService:
    """
    Service for verifying domain ownership via DNS TXT records.

    Verification process:
    1. User adds domain to their account
    2. System generates unique verification token
    3. User adds TXT record: _{BRAND_NAME}.domain.com → token
    4. User clicks "Verify Domain"
    5. System performs DNS lookup to check if TXT record matches
    6. If match → domain is verified
    """

    def __init__(self):
        """Initialize DNS resolver."""
        self.resolver = dns.resolver.Resolver()
        # Use Google's public DNS for reliability
        self.resolver.nameservers = ['8.8.8.8', '8.8.4.4']
        self.resolver.timeout = 5.0
        self.resolver.lifetime = 10.0
        self.brand_name = settings.BRAND_NAME

    def verify_domain_dns(self, domain: str, expected_token: str) -> Dict[str, any]:
        """
        Verify domain ownership by checking DNS TXT record.

        Args:
            domain: The domain to verify (e.g., "REDACTED.se")
            expected_token: The verification token that should be in DNS

        Returns:
            dict: Verification result
                {
                    "verified": bool,
                    "message": str,
                    "found_token": str | None,
                    "dns_record": str | None
                }

        Example:
            result = service.verify_domain_dns("REDACTED.se", "abc123xyz")
            if result["verified"]:
                print("Domain verified!")
        """
        # Clean domain (remove https://, www., etc.)
        clean_domain = self._clean_domain(domain)

        # Build DNS record name
        dns_record = f"_{self.brand_name}.{clean_domain}"

        logger.info(f"Attempting DNS verification for {clean_domain}")
        logger.info(f"Looking up TXT record: {dns_record}")
        logger.info(f"Expected token: {expected_token}")

        try:
            # Query TXT records
            answers = self.resolver.resolve(dns_record, 'TXT')

            # Check each TXT record
            for rdata in answers:
                # TXT records are returned as quoted strings, need to decode
                txt_value = b''.join(rdata.strings).decode('utf-8')
                logger.info(f"Found TXT record: {txt_value}")

                # Check if it matches our verification token
                if txt_value.strip() == expected_token.strip():
                    logger.info(f"✅ DNS verification successful for {clean_domain}")
                    return {
                        "verified": True,
                        "message": f"Domain verified successfully! TXT record found at {dns_record}",
                        "found_token": txt_value,
                        "dns_record": dns_record
                    }

            # TXT records found but none matched
            logger.warning(f"TXT records found for {dns_record} but none matched expected token")
            return {
                "verified": False,
                "message": f"Verification failed: TXT record found but token doesn't match. Expected: {expected_token}",
                "found_token": txt_value if answers else None,
                "dns_record": dns_record
            }

        except dns.resolver.NXDOMAIN:
            logger.warning(f"DNS record {dns_record} does not exist")
            return {
                "verified": False,
                "message": f"Verification failed: DNS record {dns_record} not found. Please add the TXT record and try again.",
                "found_token": None,
                "dns_record": dns_record
            }

        except dns.resolver.NoAnswer:
            logger.warning(f"No TXT records found for {dns_record}")
            return {
                "verified": False,
                "message": f"Verification failed: No TXT records found at {dns_record}. Please add the TXT record and wait for DNS propagation (can take up to 48h).",
                "found_token": None,
                "dns_record": dns_record
            }

        except dns.resolver.Timeout:
            logger.error(f"DNS query timeout for {dns_record}")
            return {
                "verified": False,
                "message": "Verification failed: DNS query timed out. Please try again in a few minutes.",
                "found_token": None,
                "dns_record": dns_record
            }

        except Exception as e:
            logger.error(f"DNS verification error for {clean_domain}: {e}", exc_info=True)
            return {
                "verified": False,
                "message": f"Verification failed: {str(e)}",
                "found_token": None,
                "dns_record": dns_record
            }

    def _clean_domain(self, domain: str) -> str:
        """
        Clean domain string by removing protocol, www, trailing slashes.

        Args:
            domain: Raw domain string (e.g., "https://www.REDACTED.se/")

        Returns:
            str: Cleaned domain (e.g., "REDACTED.se")
        """
        # Remove protocol
        domain = domain.replace('https://', '').replace('http://', '')

        # Remove www.
        if domain.startswith('www.'):
            domain = domain[4:]

        # Remove trailing slash
        domain = domain.rstrip('/')

        # Remove path if any
        if '/' in domain:
            domain = domain.split('/')[0]

        # Remove port if any
        if ':' in domain:
            domain = domain.split(':')[0]

        return domain.lower().strip()

    def get_verification_instructions(self, domain: str, verification_token: str) -> Dict[str, str]:
        """
        Get DNS verification instructions for user.

        Args:
            domain: The domain to verify
            verification_token: The verification token

        Returns:
            dict: Instructions
                {
                    "dns_record": str,
                    "record_type": str,
                    "record_value": str,
                    "instructions": str
                }
        """
        clean_domain = self._clean_domain(domain)
        dns_record = f"_{self.brand_name}.{clean_domain}"

        instructions = f"""
To verify ownership of {clean_domain}, add the following DNS record:

Record Type: TXT
Name: _{self.brand_name}
Host/Name: {dns_record}
Value: {verification_token}
TTL: 3600 (or default)

Steps:
1. Log in to your DNS provider (e.g., DigitalOcean, Cloudflare, GoDaddy, Namecheap)
2. Go to DNS management for {clean_domain}
3. Add a new TXT record with the values above
4. Wait 5-10 minutes for DNS propagation
5. Click 'Verify Domain' button

Note: DNS changes can take up to 48 hours to propagate globally, but usually happens within minutes.
        """.strip()

        return {
            "dns_record": dns_record,
            "record_type": "TXT",
            "record_value": verification_token,
            "instructions": instructions
        }


# Global service instance
domain_verification_service = DomainVerificationService()
