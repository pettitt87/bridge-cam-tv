#!/usr/bin/env python3
"""Re-resolve YouTube live video IDs for cameras.json.

For each camera with a `refresh` hint, fetch that channel's /streams tab,
find the currently-live video whose title contains `match` (or the first
live video if no match given), and update `vid` if it changed.
"""
import json, re, sys, time, urllib.request

UA = ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/126.0 Safari/537.36')
MENU = {'Add to queue', 'Save to playlist', 'Share', 'Download'}


def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept-Language': 'en-US,en'})
    return urllib.request.urlopen(req, timeout=30).read().decode('utf-8', 'replace')


def channel_lives(channel):
    """Return [(videoId, title)] of currently-live streams on a channel."""
    base = ('https://www.youtube.com/channel/%s' % channel
            if channel.startswith('UC') else 'https://www.youtube.com/%s' % channel)
    raw = fetch(base + '/streams')
    out, seen = [], set()
    for m in re.finditer(r'"videoId":"([A-Za-z0-9_-]{11})"', raw):
        vid = m.group(1)
        if vid in seen:
            continue
        seen.add(vid)
        block = raw[m.start():m.start() + 6000]
        if ' watching"' not in block:
            continue
        title = ''
        for tm in re.finditer(r'"title":\{"content":"(.*?)"\}', block):
            if tm.group(1) not in MENU:
                title = tm.group(1)
                break
        out.append((vid, title))
    return out


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else 'cameras.json'
    data = json.load(open(path))
    cache, changed = {}, 0

    for cam in data['cameras']:
        r = cam.get('refresh')
        if not r or cam.get('type') != 'yt':
            continue
        ch = r['channel']
        if ch not in cache:
            try:
                cache[ch] = channel_lives(ch)
                time.sleep(1)
            except Exception as e:
                print('WARN %s: %s' % (ch, e))
                cache[ch] = None
        lives = cache[ch]
        if not lives:
            continue
        match = r.get('match', '').lower()
        cand = [vid for vid, title in lives if not match or match in title.lower()]
        if cam.get('vid') in cand:
            continue  # current stream is still live and matching — don't churn
        pick = cand[0] if cand else None
        if pick and pick != cam.get('vid'):
            print('UPDATE %-12s %s -> %s' % (cam['id'], cam.get('vid'), pick))
            cam['vid'] = pick
            changed += 1
        elif not pick:
            print('NOMATCH %-12s (%s: %r)' % (cam['id'], ch, r.get('match')))

    if changed:
        json.dump(data, open(path, 'w'), indent=2, ensure_ascii=False)
        print('%d camera(s) updated' % changed)
    else:
        print('all IDs current')
    # exit 0 either way; the workflow only commits when the file differs


if __name__ == '__main__':
    main()
