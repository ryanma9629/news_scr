#!/usr/bin/env python3
"""
SSL Certificate Generator

This script generates self-signed SSL certificates for development and testing purposes.
The certificates are suitable for localhost HTTPS testing but should not be used in production.
"""

import datetime
import ipaddress
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization


def generate_ssl_certificate(cert_file="cert.pem", key_file="key.pem", days=365):
    """Generate a self-signed SSL certificate for localhost."""
    
    print(f"Generating SSL certificate: {cert_file}, key: {key_file}")
    
    # Generate private key
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    
    # Create certificate subject
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "Development"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, "Local"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "News Search App"),
        x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
    ])
    
    # Create certificate
    cert = x509.CertificateBuilder().subject_name(
        subject
    ).issuer_name(
        issuer
    ).public_key(
        private_key.public_key()
    ).serial_number(
        x509.random_serial_number()
    ).not_valid_before(
        datetime.datetime.now(datetime.timezone.utc)
    ).not_valid_after(
        datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=days)
    ).add_extension(
        x509.SubjectAlternativeName([
            x509.DNSName("localhost"),
            x509.DNSName("127.0.0.1"),
            x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
            x509.IPAddress(ipaddress.IPv6Address("::1")),
        ]),
        critical=False,
    ).sign(private_key, hashes.SHA256())
    
    # Write certificate to file
    with open(cert_file, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    
    # Write private key to file
    with open(key_file, "wb") as f:
        f.write(private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        ))
    
    print("✓ SSL certificate generated successfully!")
    print(f"  Certificate: {cert_file}")
    print(f"  Private key: {key_file}")
    print(f"  Valid for: {days} days")
    print("  Note: This is a self-signed certificate for development only.")
    

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Generate self-signed SSL certificates")
    parser.add_argument("--cert", default="cert.pem", help="Certificate file name (default: cert.pem)")
    parser.add_argument("--key", default="key.pem", help="Private key file name (default: key.pem)")
    parser.add_argument("--days", type=int, default=365, help="Certificate validity in days (default: 365)")
    
    args = parser.parse_args()
    
    try:
        generate_ssl_certificate(args.cert, args.key, args.days)
    except Exception as e:
        print(f"Error generating SSL certificate: {e}")
        exit(1)
