<?php
/**
 * ProfAlgoLabs™ visitor counter.
 * POST = record a visit (once per browser session, called by the page), GET = read the totals.
 * Counts total visits and unique visitors per day. IP addresses are never stored: each visitor
 * is a salted, daily-rotating hash, so nobody can be tracked across days.
 */
declare(strict_types=1);
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');
header('X-Content-Type-Options: nosniff');

const DATA_DIR = __DIR__ . '/data';
const STATS    = DATA_DIR . '/visits.json';
const START_AT = 0;   // set a starting number here if you want to carry over a count from an older counter

function out(array $a): void { echo json_encode($a); exit; }
if (!is_dir(DATA_DIR)) { @mkdir(DATA_DIR, 0750, true); }

$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
$ua = $_SERVER['HTTP_USER_AGENT'] ?? '';
$isBot = $ua === '' || preg_match('/bot|crawl|spider|slurp|facebookexternalhit|preview|monitor|curl|wget|python|headless/i', $ua);
$origin = $_SERVER['HTTP_ORIGIN'] ?? ($_SERVER['HTTP_REFERER'] ?? '');
$sameSite = $origin === '' || preg_match('~^https?://([a-z0-9-]+\.)*algoprofessor\.com(/|:|$)~i', $origin);

$fh = fopen(STATS, 'c+');
if (!$fh) out(['ok' => false]);
flock($fh, $method === 'POST' ? LOCK_EX : LOCK_SH);
$raw = stream_get_contents($fh);
$s = json_decode($raw ?: '', true) ?: ['total' => START_AT, 'uniqueTotal' => 0, 'day' => '', 'today' => 0, 'todayUnique' => 0, 'seen' => [], 'salt' => bin2hex(random_bytes(16))];

$today = gmdate('Y-m-d');
if ($s['day'] !== $today) {                 // new day: reset daily figures and rotate the salt
  $s['day'] = $today; $s['today'] = 0; $s['todayUnique'] = 0; $s['seen'] = []; $s['salt'] = bin2hex(random_bytes(16));
}

if ($method === 'POST' && !$isBot && $sameSite) {
  $s['total']++; $s['today']++;
  $h = substr(hash('sha256', $s['salt'] . '|' . ($_SERVER['REMOTE_ADDR'] ?? '') . '|' . $ua), 0, 20);
  if (!isset($s['seen'][$h])) { $s['seen'][$h] = 1; $s['todayUnique']++; $s['uniqueTotal']++; }
  if (count($s['seen']) > 50000) { $s['seen'] = array_slice($s['seen'], -25000, null, true); }
  ftruncate($fh, 0); rewind($fh); fwrite($fh, json_encode($s)); fflush($fh);
}
flock($fh, LOCK_UN); fclose($fh);
out(['ok' => true, 'total' => (int)$s['total'], 'unique' => (int)$s['uniqueTotal'], 'today' => (int)$s['today'], 'todayUnique' => (int)$s['todayUnique']]);
