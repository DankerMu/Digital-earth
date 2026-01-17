#!/usr/bin/env bash
set -euo pipefail

base_url="${1:-}"
if [[ -z "${base_url}" ]]; then
  echo "Usage: $0 <BASE_URL>"
  echo "Example: $0 https://example.com"
  exit 2
fi

http_code() {
  curl -s -o /dev/null -w "%{http_code}" "$1"
}

pass=true

echo "== Normal traffic (should NOT be blocked as 403) =="
normal_urls=(
  "${base_url}/"
  "${base_url}/api/v1"
)

for url in "${normal_urls[@]}"; do
  code="$(http_code "${url}")"
  if [[ "${code}" == "403" || "${code}" == 5* ]]; then
    echo "FAIL ${code} ${url}"
    pass=false
  else
    echo "OK   ${code} ${url}"
  fi
done

echo
echo "== Attack traffic (should be blocked as 403) =="
attack_urls=(
  "${base_url}/.env"
  "${base_url}/.git/config"
  "${base_url}/api/v1/search?q=1%20union%20select%201,2,3"
  "${base_url}/?q=%3Cscript%3Ealert(1)%3C%2Fscript%3E"
)

for url in "${attack_urls[@]}"; do
  code="$(http_code "${url}")"
  if [[ "${code}" != "403" ]]; then
    echo "FAIL ${code} ${url}"
    pass=false
  else
    echo "OK   ${code} ${url}"
  fi
done

echo
if [[ "${pass}" == "true" ]]; then
  echo "PASS: WAF behavior matches expectations."
  exit 0
fi

echo "FAIL: WAF behavior does not match expectations."
echo "Tips:"
echo "- Confirm ingress-nginx controller ConfigMap has ModSecurity enabled (see infra/k8s/waf-rules.yaml)."
echo "- Confirm Ingress has enable-modsecurity/enable-owasp-core-rules annotations."
echo "- Check controller logs for 'WAF:' messages."
exit 1

