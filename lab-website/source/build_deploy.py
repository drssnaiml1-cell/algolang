import re, hashlib, base64, json
SITE="https://www.profagentlabs.algoprofessor.com/"
s=open("profalgolabs.html",encoding="utf-8").read()
cut=s.index("</style>")+len("</style>")
headpart, body = s[:cut], s[cut:]
extra=f'''<link rel="icon" type="image/svg+xml" href="/assets/favicon.svg">
<link rel="apple-touch-icon" href="/assets/apple-touch-icon.png">
<link rel="manifest" href="/site.webmanifest">
<meta property="og:image" content="{SITE}assets/og-image.png">
<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">
<meta property="og:image:alt" content="ProfAlgoLabs — Where agents replace functions">
<meta name="twitter:image" content="{SITE}assets/og-image.png">
<meta name="format-detection" content="telephone=no">
'''
headpart=headpart.replace('<meta name="claude:viewport-fit-sides" content="cover">\n','')
html=('<!doctype html>\n<html lang="en-IN">\n<head>\n<meta charset="utf-8">\n'
      '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">\n'
      +extra+headpart+'\n<noscript><style>.reveal.pre{opacity:1;transform:none}</style></noscript>\n</head>\n<body>\n'+body+'\n</body>\n</html>\n')
open("deploy/index.html","w",encoding="utf-8").write(html)
# CSP hashes for every inline <script> that executes (incl. importmap; JSON-LD doesn't execute)
hashes=[]
for m in re.finditer(r'<script(?P<a>[^>]*)>(?P<c>.*?)</script>',html,re.S):
    if 'src=' in m['a'] or 'ld+json' in m['a']: continue
    hashes.append("'sha256-"+base64.b64encode(hashlib.sha256(m['c'].encode()).digest()).decode()+"'")
csp=("default-src 'self'; script-src 'self' "+" ".join(hashes)+" https://cdn.jsdelivr.net; "
     "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; "
     "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'; upgrade-insecure-requests")
ht=f'''# ProfAlgoLabs — security, HTTPS and caching (Apache / cPanel)
Options -Indexes
ServerSignature Off
DirectoryIndex index.html
AddDefaultCharset UTF-8

<IfModule mod_rewrite.c>
  RewriteEngine On
  # Force HTTPS
  RewriteCond %{{HTTPS}} !=on
  RewriteCond %{{HTTP:X-Forwarded-Proto}} !https
  RewriteRule ^ https://%{{HTTP_HOST}}%{{REQUEST_URI}} [L,R=301]
  # Block hidden files (.git, .env …) but allow .well-known for SSL
  RewriteRule "(^|/)\\.(?!well-known/)" - [F]
</IfModule>

<IfModule mod_headers.c>
  Header always set Strict-Transport-Security "max-age=31536000; includeSubDomains"
  Header always set X-Content-Type-Options "nosniff"
  Header always set X-Frame-Options "DENY"
  Header always set Referrer-Policy "strict-origin-when-cross-origin"
  Header always set Permissions-Policy "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
  Header always set Cross-Origin-Opener-Policy "same-origin"
  Header always unset X-Powered-By
  <FilesMatch "\\.html$">
    Header always set Content-Security-Policy "{csp}"
    Header set Cache-Control "no-cache"
  </FilesMatch>
  <FilesMatch "\\.(png|svg|webmanifest|ico)$">
    Header set Cache-Control "public, max-age=2592000"
  </FilesMatch>
</IfModule>

# Never serve data, logs, backups or source files
<FilesMatch "\\.(csv|json|log|bak|sql|ini|md|zip|py|sh)$">
  Require all denied
</FilesMatch>
<Files "site.webmanifest">
  Require all granted
</Files>

<IfModule mod_deflate.c>
  AddOutputFilterByType DEFLATE text/html text/css application/javascript application/json image/svg+xml application/manifest+json
</IfModule>
AddType application/manifest+json .webmanifest
ErrorDocument 404 /index.html
'''
open("deploy/.htaccess","w").write(ht)
open("deploy/data/.htaccess","w").write("# Private: enquiries and visitor stats\nRequire all denied\n<IfModule !mod_authz_core.c>\n  Deny from all\n</IfModule>\n")
open("deploy/robots.txt","w").write(f"User-agent: *\nAllow: /\nDisallow: /data/\nDisallow: /contact.php\nDisallow: /counter.php\n\nSitemap: {SITE}sitemap.xml\n")
open("deploy/sitemap.xml","w").write(f'''<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>{SITE}</loc><lastmod>2026-10-29</lastmod><changefreq>weekly</changefreq><priority>1.0</priority></url>
</urlset>
''')
open("deploy/site.webmanifest","w").write(json.dumps({"name":"ProfAlgoLabs™ · AlgoProfessor","short_name":"ProfAlgoLabs","start_url":"/","display":"standalone",
  "background_color":"#050c1a","theme_color":"#071328","icons":[{"src":"/assets/icon-512.png","sizes":"512x512","type":"image/png"},{"src":"/assets/apple-touch-icon.png","sizes":"180x180","type":"image/png"}]},indent=2,ensure_ascii=False))
logo='''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40"><rect width="40" height="40" rx="9" fill="#071328"/><circle cx="20" cy="20" r="16.5" fill="none" stroke="#d9b54a" stroke-width="1.4" stroke-dasharray="3 3.2"/><path d="M20 10.5 L28.6 26 H11.4 Z" fill="none" stroke="#eef2f8" stroke-width="1.8" stroke-linejoin="round"/><circle cx="20" cy="10.5" r="2.7" fill="#f1d27a"/><circle cx="28.6" cy="26" r="2.7" fill="#d9b54a"/><circle cx="11.4" cy="26" r="2.7" fill="#d9b54a"/><circle cx="20" cy="21" r="2" fill="#eef2f8"/></svg>'''
open("deploy/assets/favicon.svg","w").write(logo)
print("hashes",len(hashes))
