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


def _first_video_id(obj):
    """Depth-first search for the first videoId string in a JSON subtree."""
    if isinstance(obj, dict):
        if isinstance(obj.get('videoId'), str):
            return obj['videoId']
        for v in obj.values():
            r = _first_video_id(v)
            if r:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _first_video_id(v)
            if r:
                return r
    return None


def _walk_lockups(obj, out, seen):
    """Collect (videoId, title) from live lockupViewModel nodes."""
    if isinstance(obj, dict):
        lv = obj.get('lockupViewModel')
        if isinstance(lv, dict):
            dump = json.dumps(lv)
            if 'THUMBNAIL_OVERLAY_BADGE_STYLE_LIVE' in dump:
                vid = _first_video_id(lv)
                if vid and vid not in seen:
                    seen.add(vid)
                    title = ''
                    try:
                        title = lv['metadata']['lockupMetadataViewModel']['title']['content']
                    except (KeyError, TypeError):
                        pass
                    out.append((vid, title))
        for v in obj.values():
            _walk_lockups(v, out, seen)
    elif isinstance(obj, list):
        for v in obj:
            _walk_lockups(v, out, seen)


def _find_continuation(obj):
    if isinstance(obj, dict):
        cc = obj.get('continuationCommand')
        if isinstance(cc, dict) and isinstance(cc.get('token'), str):
            return cc['token']
        for v in obj.values():
            r = _find_continuation(v)
            if r:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _find_continuation(v)
            if r:
                return r
    return None


def channel_lives(channel):
    """Return [(videoId, title)] of currently-live streams, walking all pages."""
    base = ('https://www.youtube.com/channel/%s' % channel
            if channel.startswith('UC') else 'https://www.youtube.com/%s' % channel)
    raw = fetch(base + '/streams')
    m = re.search(r'var ytInitialData = (\{.*?\});</script>', raw)
    if not m:
        return []
    data = json.loads(m.group(1))
    out, seen = [], set()
    _walk_lockups(data, out, seen)
    tok, pages = _find_continuation(data), 0
    while tok and pages < 12:
        body = json.dumps({
            'context': {'client': {'clientName': 'WEB', 'clientVersion': '2.20250725.01.00'}},
            'continuation': tok}).encode()
        req = urllib.request.Request(
            'https://www.youtube.com/youtubei/v1/browse', data=body,
            headers={'Content-Type': 'application/json', 'User-Agent': UA})
        try:
            obj = json.load(urllib.request.urlopen(req, timeout=30))
        except Exception:
            break
        _walk_lockups(obj, out, seen)
        pages += 1
        tok = _find_continuation(obj)
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
