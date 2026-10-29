<?php
/**
 * ProfAlgoLabs™ contact form handler (cPanel, PHP 7.4+).
 * Emails each enquiry to ceo@algoprofessor.com and keeps a CSV copy in /data (blocked from the web).
 *
 * Protection layers:
 *   1. Same-site check (Origin / Referer must be *.algoprofessor.com)
 *   2. One-time form token held in a secure, HttpOnly, SameSite=Strict session cookie
 *   3. Time trap: the form must be open for at least 3 seconds
 *   4. Honeypot field ("website") that people never see
 *   5. Rate limit: 5 enquiries per hour per connection (IP stored only as a salted hash)
 *   6. Strict validation, header-injection removal, spreadsheet-formula neutralising
 */
declare(strict_types=1);
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');
header('X-Content-Type-Options: nosniff');

// ── settings ─────────────────────────────────────────────
const TO_EMAIL   = 'ceo@algoprofessor.com';
const CC_EMAIL   = '';                           // optional, e.g. 'contact@algoprofessor.com'
const FROM_EMAIL = 'no-reply@algoprofessor.com'; // create this mailbox or forwarder in cPanel
const DATA_DIR   = __DIR__ . '/data';
const MAX_PER_HOUR = 5;
const MIN_SECONDS  = 3;
$SERVICES = [
  'lang' => 'Programming Language & Compiler Development', 'agentic' => 'Agentic AI Systems & Products',
  'security' => 'Enterprise AI Security & Supply-Chain Assurance', 'quant' => 'Quant Research & Algo Trading Strategies',
  'q1' => 'Q1 SCI Research & Publication Support', 'courses' => 'AI Courses & Certification',
  'intern' => 'Live Internships & Forward Deployed Engineering', 'campus' => 'University Partnerships & AlgoProfessor Campus',
  'pubs' => 'AlgoProfessor Publications', 'applied' => 'Applied AI Products & Development', 'other' => 'Something else',
];
$ENGAGE = ['Project', 'Training', 'Partnership', 'Research collaboration', 'Investment'];

session_name('pal_s');
session_set_cookie_params(['lifetime' => 0, 'path' => '/', 'secure' => !empty($_SERVER['HTTPS']), 'httponly' => true, 'samesite' => 'Strict']);
session_start();

function reply(int $code, array $body): void {
  // every reply carries a fresh token so the form can be sent again
  $_SESSION['pal_token'] = bin2hex(random_bytes(24)); $_SESSION['pal_token_at'] = time();
  $body['token'] = $_SESSION['pal_token'];
  http_response_code($code); echo json_encode($body); exit;
}
function field(string $k, int $max): string {
  $v = (string)($_POST[$k] ?? '');
  $v = str_replace(["\r", "\0"], '', $v);
  return trim(mb_substr($v, 0, $max));
}
function oneLine(string $v): string { return trim(preg_replace('/[\n\t]+/', ' ', $v)); }

// Token request (page load)
if ($_SERVER['REQUEST_METHOD'] === 'GET' && isset($_GET['token'])) reply(200, ['ok' => true]);
if ($_SERVER['REQUEST_METHOD'] !== 'POST') reply(405, ['ok' => false, 'error' => 'Use the form to send an enquiry.']);

// 1. same-site
$origin = $_SERVER['HTTP_ORIGIN'] ?? ($_SERVER['HTTP_REFERER'] ?? '');
if (!preg_match('~^https?://([a-z0-9-]+\.)*algoprofessor\.com(/|:|$)~i', $origin)) {
  reply(403, ['ok' => false, 'error' => 'This form only accepts enquiries from algoprofessor.com.']);
}
// 4. honeypot (pretend success so bots learn nothing)
if (field('website', 200) !== '') reply(200, ['ok' => true, 'ref' => 'OK']);
// 2. token
$sent = field('token', 100);
if (empty($_SESSION['pal_token']) || !hash_equals((string)$_SESSION['pal_token'], $sent)) {
  reply(400, ['ok' => false, 'error' => 'Your session expired. Please press Send again.']);
}
// 3. time trap
if (time() - (int)($_SESSION['pal_token_at'] ?? 0) < MIN_SECONDS) {
  reply(400, ['ok' => false, 'error' => 'That was very fast. Please check your message and press Send again.']);
}
// 5. rate limit
if (!is_dir(DATA_DIR)) { @mkdir(DATA_DIR, 0750, true); }
$ipHash = substr(hash('sha256', ($_SERVER['REMOTE_ADDR'] ?? '') . '|' . __FILE__), 0, 16);
$rateFile = DATA_DIR . '/rate_' . $ipHash . '.json';
$now = time();
$hits = is_file($rateFile) ? array_values(array_filter((array)json_decode((string)file_get_contents($rateFile), true), fn($t) => $t > $now - 3600)) : [];
if (count($hits) >= MAX_PER_HOUR) reply(429, ['ok' => false, 'error' => 'Too many enquiries from this connection. Please try again in an hour.']);

// 6. validate
$name = oneLine(field('name', 120));      $email = oneLine(field('email', 160));
$phone = oneLine(field('phone', 30));     $org = oneLine(field('organisation', 160));
$role = oneLine(field('role', 80));       $country = oneLine(field('country', 80));
$svcId = oneLine(field('service', 20));   $engage = oneLine(field('engagement', 40));
$budget = oneLine(field('budget', 40));   $timeline = oneLine(field('timeline', 40));
$message = field('message', 4000);        $consent = isset($_POST['consent']);
$errors = [];
if (mb_strlen($name) < 2) $errors[] = 'Enter your full name.';
if (!filter_var($email, FILTER_VALIDATE_EMAIL)) $errors[] = 'Enter a valid email address.';
if ($phone !== '' && !preg_match('/^[+()\d\s-]{7,30}$/', $phone)) $errors[] = 'Check the phone number.';
if (!isset($SERVICES[$svcId])) $errors[] = 'Choose the service this is about.';
if (!in_array($engage, $ENGAGE, true)) $engage = 'Project';
if (mb_strlen($message) < 20) $errors[] = 'Tell us a little more: at least 20 characters.';
if (preg_match_all('~https?://~i', $message) > 3) $errors[] = 'Please include no more than three links.';
if (!$consent) $errors[] = 'Tick the consent box so we can reply to you.';
if ($errors) reply(422, ['ok' => false, 'error' => implode(' ', $errors)]);

$service = $SERVICES[$svcId];
$ref = strtoupper(substr(bin2hex(random_bytes(6)), 0, 8));
$when = gmdate('Y-m-d H:i:s') . ' UTC';
$clean = fn($v) => str_replace(["\r", "\n", '<', '>'], ' ', $v);   // header-safe

$subject = "[ProfAlgoLabs] {$service} — {$name} (ref {$ref})";
$body = "New enquiry from the ProfAlgoLabs website\n\nReference:    {$ref}\nReceived:     {$when}\n\n"
      . "Name:         {$name}\nEmail:        {$email}\nPhone:        {$phone}\nOrganisation: {$org}\nRole:         {$role}\nCountry:      {$country}\n\n"
      . "Service:      {$service}\nEngagement:   {$engage}\nBudget:       {$budget}\nStart:        {$timeline}\n\nMessage:\n{$message}\n";
$headers = ['From: ProfAlgoLabs Website <' . FROM_EMAIL . '>', 'Reply-To: ' . $clean($name) . ' <' . $clean($email) . '>',
            'MIME-Version: 1.0', 'Content-Type: text/plain; charset=UTF-8', 'X-Mailer: ProfAlgoLabs'];
if (CC_EMAIL !== '') $headers[] = 'Cc: ' . CC_EMAIL;
$mailed = @mail(TO_EMAIL, '=?UTF-8?B?' . base64_encode($subject) . '?=', $body, implode("\r\n", $headers), '-f' . FROM_EMAIL);

// CSV copy, kept even if mail fails so no enquiry is lost
$csv = DATA_DIR . '/enquiries.csv'; $new = !is_file($csv); $saved = false;
if ($fh = @fopen($csv, 'a')) {
  if (flock($fh, LOCK_EX)) {
    if ($new) fputcsv($fh, ['ref','received_utc','name','email','phone','organisation','role','country','service','engagement','budget','timeline','message','emailed']);
    $safe = fn($v) => preg_match('/^[=+\-@\t]/', (string)$v) ? "'" . $v : $v;
    $saved = fputcsv($fh, array_map($safe, [$ref,$when,$name,$email,$phone,$org,$role,$country,$service,$engage,$budget,$timeline,$message,$mailed?'yes':'no'])) !== false;
    flock($fh, LOCK_UN);
  }
  fclose($fh);
}
$hits[] = $now; @file_put_contents($rateFile, json_encode($hits), LOCK_EX);
if (!$mailed && !$saved) reply(500, ['ok' => false, 'error' => 'The server could not record your enquiry.']);
reply(200, ['ok' => true, 'ref' => $ref]);
