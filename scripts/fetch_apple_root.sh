#!/usr/bin/env sh
# Downloads Apple's App Attestation root CA, which the API pins to verify iOS
# attestations. Check the fingerprint against the one Apple publishes before use.
set -eu
out="${1:-config/Apple_App_Attestation_Root_CA.pem}"
curl -fsSL -o "$out" https://www.apple.com/certificateauthority/Apple_App_Attestation_Root_CA.pem
openssl x509 -in "$out" -noout -subject -enddate -fingerprint -sha256
echo "saved to $out"
