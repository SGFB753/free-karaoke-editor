#!/usr/bin/env python3
"""Fixing a single line in timings.json by hand — when giving the time is easier.

    py tools\\fix_line.py timings.json --list
    py tools\\fix_line.py timings.json --line 34 --start 150.0
    py tools\\fix_line.py timings.json --find "Присесть" --near 135 --start 150.0
    py tools\\fix_line.py timings.json --line 34 --shift +14.9 --and-after

Если под --find подходит несколько строк (припев повторяется), программа
покажет их все с номерами и временем и не станет угадывать: уточните
номером --line, ближайшим временем --near или порядковым номером --nth.

Слова строки едут вместе с ней, промежутки между ними сохраняются, поэтому
заливка остаётся плавной. Файл переписывается на месте, рядом кладётся
резервная копия с расширением .bak.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys


def mmss(t) -> str:
    return f"{int(t // 60)}:{t % 60:06.3f}"


def parse_time(s: str) -> float:
    """Seconds, or a time like 2:30.81 / 2:30,81 / 2:30:81 — whichever is handier."""
    s = str(s).strip().replace(",", ".")
    if ":" not in s:
        return float(s)
    parts = s.split(":")
    if len(parts) == 2:                       # М:СС.ддд
        return int(parts[0]) * 60 + float(parts[1])
    if len(parts) == 3:                       # М:СС:ддд — доли после второго двоеточия
        frac = parts[2]
        return int(parts[0]) * 60 + int(parts[1]) + float("0." + frac)
    raise SystemExit(f"Не понял время «{s}». Пишите 150.81 или 2:30.81")


def tidy_line(line: dict, max_gap: float = 1.2) -> bool:
    """Put back together a line whose words drifted apart in time.

    Та же логика, что при сборке страницы: внутри спетой строки многосекундных
    провалов не бывает. Отбившиеся слова подтягиваем к основному скоплению.
    """
    ws = line.get("words") or []
    if len(ws) < 2:
        return False

    groups, cur = [], [ws[0]]
    for prev, w in zip(ws, ws[1:]):
        if w["t"] - (prev["t"] + prev["d"]) > max_gap:
            groups.append(cur)
            cur = [w]
        else:
            cur.append(w)
    groups.append(cur)
    if len(groups) < 2:
        return False

    best = max(groups, key=lambda g: sum(x.get("s", 1) for x in g))
    s, e = best[0]["t"], best[-1]["t"] + best[-1]["d"]
    bi = ws.index(best[0])

    def spread(chunk, a, b):
        total = sum(x.get("s", 1) or 1 for x in chunk) or 1
        span = max(b - a, 0.05)
        acc = 0.0
        for x in chunk:
            x["t"] = round(a + span * acc / total, 3)
            acc += x.get("s", 1) or 1
            x["d"] = round(a + span * acc / total - x["t"], 3)

    before, after = ws[:bi], ws[bi + len(best):]
    if before:
        need = min(0.35 * sum(x.get("s", 1) for x in before), 2.0)
        spread(before, max(s - need, 0.0), s)
    if after:
        need = min(0.35 * sum(x.get("s", 1) for x in after), 2.0)
        spread(after, e, e + need)

    line["start"] = round(ws[0]["t"], 3)
    line["end"] = round(ws[-1]["t"] + ws[-1]["d"], 3)
    return True


def load(path: str) -> dict:
    with open(path, encoding="utf-8-sig") as f:
        data = json.load(f)
    if not isinstance(data, dict) or "lines" not in data:
        raise SystemExit(f"{path} — не похоже на файл таймингов из плеера.")
    return data


def pick(data: dict, args) -> int:
    lines = data["lines"]
    if args.line is not None:
        i = args.line - 1
        if not 0 <= i < len(lines):
            raise SystemExit(f"В файле {len(lines)} строк, а запрошена {args.line}.")
        return i

    needle = args.find.lower()
    hits = [i for i, l in enumerate(lines) if needle in (l.get("text") or "").lower()]
    if not hits:
        raise SystemExit(f"Строк со словами «{args.find}» не нашлось.")
    if len(hits) == 1:
        return hits[0]

    # Repeated lines are normal in a song, so we ask instead of guessing.
    if args.near is not None:
        i = min(hits, key=lambda k: abs(lines[k]["start"] - args.near))
        print(f"Из {len(hits)} совпадений взял ближайшее к {mmss(args.near)}: "
              f"строка {i+1} на {mmss(lines[i]['start'])}")
        return i
    if args.nth is not None:
        if not 1 <= args.nth <= len(hits):
            raise SystemExit(f"Совпадений {len(hits)}, а запрошено {args.nth}-е.")
        return hits[args.nth - 1]

    print(f"Под «{args.find}» подходит несколько строк:")
    for k, i in enumerate(hits, 1):
        print(f"  {i+1:3}. [{mmss(lines[i]['start'])} — {mmss(lines[i]['end'])}]"
              f"  {lines[i]['text']}     (это {k}-е совпадение)")
    raise SystemExit(
        "Уточните любым из способов:\n"
        f"    --line {hits[0]+1}          — точный номер строки\n"
        f"    --near {lines[hits[0]]['start']:.0f}          — та, что сейчас стоит около этой секунды\n"
        f"    --nth 1              — первое совпадение по порядку")


def shift_line(line: dict, dt: float) -> None:
    line["start"] = round(line["start"] + dt, 3)
    line["end"] = round(line["end"] + dt, 3)
    for w in line.get("words") or []:
        w["t"] = round(w["t"] + dt, 3)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="fix_line.py", description="Подвинуть строку в timings.json вручную.",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument("json", help="файл таймингов, скачанный из плеера")
    p.add_argument("--list", action="store_true", help="показать все строки с временами")
    p.add_argument("--line", type=int, help="номер строки (как в --list)")
    p.add_argument("--find", help="кусок текста строки")
    p.add_argument("--near", type=parse_time, metavar="ВРЕМЯ",
                   help="если совпадений несколько — взять ту, что стоит около этого времени")
    p.add_argument("--nth", type=int, metavar="N",
                   help="если совпадений несколько — взять N-е по порядку")
    p.add_argument("--start", type=parse_time, metavar="ВРЕМЯ",
                   help="поставить начало строки сюда: 150.81 или 2:30.81")
    p.add_argument("--shift", type=float, metavar="СЕК",
                   help="сдвинуть на столько секунд (можно минус)")
    p.add_argument("--and-after", action="store_true",
                   help="сдвинуть заодно все следующие строки на столько же")
    p.add_argument("--no-tidy", action="store_true",
                   help="не собирать разъехавшиеся слова внутри строки")
    p.add_argument("-o", "--output", help="записать в другой файл")
    args = p.parse_args(argv)

    if not os.path.isfile(args.json):
        print(f"Не найден файл: {args.json}", file=sys.stderr)
        return 2
    data = load(args.json)
    lines = data["lines"]

    if args.list:
        for i, l in enumerate(lines, 1):
            print(f"  {i:3}. [{mmss(l['start'])} — {mmss(l['end'])}] {l['text']}")
        return 0

    if args.line is None and not args.find:
        print("Укажите строку: --line N или --find \"кусок текста\". "
              "Список — с ключом --list.", file=sys.stderr)
        return 2
    if args.start is None and args.shift is None:
        print("Укажите, что сделать: --start СЕКУНДА или --shift СЕКУНД.", file=sys.stderr)
        return 2

    i = pick(data, args)
    line = lines[i]
    dt = (args.start - line["start"]) if args.start is not None else args.shift

    print(f"Строка {i+1}: {line['text']}")
    print(f"  было : {mmss(line['start'])} — {mmss(line['end'])}")

    targets = lines[i:] if args.and_after else [line]
    for l in targets:
        shift_line(l, dt)

    if not args.no_tidy and tidy_line(line):
        print("  собрал разъехавшиеся слова строки в одно место")
        if args.start is not None and abs(line["start"] - args.start) > 0.001:
            shift_line(line, args.start - line["start"])   # держим заданное начало

    print(f"  стало: {mmss(line['start'])} — {mmss(line['end'])}"
          f"   (сдвиг {dt:+.3f} с)")
    if args.and_after and len(targets) > 1:
        print(f"  вместе с ней сдвинуто строк: {len(targets)}")

    # warn if the line now overlaps its neighbours — never break things quietly
    if i and lines[i-1]["end"] > line["start"]:
        print(f"  ВНИМАНИЕ: налезает на предыдущую строку "
              f"(она кончается в {mmss(lines[i-1]['end'])})")
    if i + 1 < len(lines) and line["end"] > lines[i+1]["start"]:
        print(f"  ВНИМАНИЕ: налезает на следующую строку "
              f"(она начинается в {mmss(lines[i+1]['start'])})")

    out = args.output or args.json
    if out == args.json:
        shutil.copy2(args.json, args.json + ".bak")
        print(f"  резервная копия: {os.path.basename(args.json)}.bak")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"\nЗаписано: {out}")
    print("Теперь пересоберите песню с этим файлом через --timings.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
