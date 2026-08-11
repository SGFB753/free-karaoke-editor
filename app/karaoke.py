#!/usr/bin/env python3
"""
Караоке из аудиофайла и текста песни → один HTML-файл, который открывается
в любом браузере на любой ОС без интернета.

    python karaoke.py песня.mp3 текст.txt -o караоке.html

Полная версия с минусовкой и точной разметкой по словам:

    pip install stable-ts demucs
    python karaoke.py песня.mp3 текст.txt -o караоке.html --align whisper
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kstudio import align as A
from kstudio.i18n import tr
from kstudio import audio as AU
from kstudio import build as B
from kstudio import lyrics as L
from kstudio import separate as S

T0 = time.time()


def log(msg: str) -> None:
    print(f"[{time.time() - T0:5.1f}s] {msg}", flush=True)


def _have_whisper() -> bool:
    try:
        import stable_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def human_size(n: float) -> str:
    units = (tr("B", "Б"), tr("KB", "КБ"), tr("MB", "МБ"), tr("GB", "ГБ"))
    for i, unit in enumerate(units):
        if n < 1024 or i == len(units) - 1:
            return f"{n:.0f} {unit}" if i == 0 else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} {units[-1]}"


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="karaoke.py",
        description="Собирает автономную караоке-страницу из аудио и текста песни.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""примеры:
  python karaoke.py song.mp3 lyrics.txt
  python karaoke.py song.mp3 lyrics.txt -o out.html --align whisper --whisper-model medium
  python karaoke.py song.mp3 lyrics.txt --no-separate          # быстро, без минусовки
  python karaoke.py song.mp3 lyrics.txt --timings timings.json # применить ручную правку
""")
    p.add_argument("audio", help="аудиофайл песни (mp3, wav, flac, m4a, ogg…)")
    p.add_argument("lyrics", help="текстовый файл с текстом песни (UTF-8)")
    p.add_argument("-o", "--output", help="куда сохранить HTML (по умолчанию рядом с аудио)")

    g = p.add_argument_group("разметка")
    g.add_argument("--align", choices=["auto", "whisper", "energy", "none"], default="auto",
                   help="движок выравнивания текста по звуку (по умолчанию auto)")
    g.add_argument("--whisper-model", default="medium",
                   help="модель Whisper: tiny/base/small/medium/large-v3 (по умолчанию medium)")
    g.add_argument("--colors", default="#4de1ff,#ff8ad1",
                   help="цвета подсветки: основной голос и второй, через запятую")
    g.add_argument("--theme", default="",
                   help="цвета оформления: фон и текст через запятую, "
                        "например \"#0a0b14,#e8ebf5\"")
    g.add_argument("--ui-lang", default="auto", choices=["auto", "en", "ru"],
                   help="язык надписей готовой страницы (auto — по языку браузера)")
    g.add_argument("--lang", default="auto",
                   help="язык текста: auto (по тексту), ru, uk, en, de, fr, es, it, pl…")
    g.add_argument("--device", default=None, help="cuda | cpu (по умолчанию автоопределение)")
    g.add_argument("--timings", help="взять готовые тайминги из JSON (экспорт из плеера)")

    g = p.add_argument_group("звук")
    g.add_argument("--no-separate", action="store_true",
                   help="не отделять вокал (быстрее, но без минусовки)")
    g.add_argument("--demucs-model", default="htdemucs", help="модель Demucs")
    g.add_argument("--codec", choices=list(AU.CODECS), default="mp3",
                   help="кодек для встроенного звука (mp3 — максимальная совместимость)")

    g = p.add_argument_group("вывод")
    g.add_argument("--no-embed", action="store_true",
                   help="не встраивать звук в HTML, положить файлы рядом")
    g.add_argument("--lrc", action="store_true", help="дополнительно сохранить .lrc")
    g.add_argument("--title", help="название песни в шапке страницы")
    g.add_argument("--artist", help="исполнитель в шапке страницы")
    g.add_argument("--keep-temp", action="store_true", help="не удалять рабочую папку")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)

    for path in (args.audio, args.lyrics):
        if not os.path.isfile(path):
            print(tr(f"File not found: {path}", f"Файл не найден: {path}"), file=sys.stderr)
            return 2

    out_html = args.output or os.path.splitext(args.audio)[0] + "_karaoke.html"
    out_dir = os.path.dirname(os.path.abspath(out_html)) or "."
    os.makedirs(out_dir, exist_ok=True)

    if args.lang.lower() in ("авто", "сам"):
        args.lang = "auto"

    lyr = L.load(args.lyrics)
    if not lyr.lines:
        print(tr("The lyrics file has no lines at all.",
                 "В файле с текстом не нашлось ни одной строки."), file=sys.stderr)
        return 2
    log(tr(f"Lyrics: {len(lyr.lines)} lines, {len(lyr.words)} words.",
           f"Текст: {len(lyr.lines)} строк, {len(lyr.words)} слов."))

    tmp = tempfile.mkdtemp(prefix="karaoke_")
    try:
        AU.ffmpeg()          # ранняя понятная ошибка, если ffmpeg не установлен
        AU.ensure_on_path()  # чтобы Whisper и Demucs тоже смогли его запустить

        # Предупреждаем заранее: падение по памяти на середине выглядит как
        # набор системных кодов, по которым непонятно, что делать.
        from kstudio import sysinfo
        need = 0.5
        if not args.no_separate and S.available():
            need = max(need, sysinfo.NEED_DEMUCS)
        if args.align in ("auto", "whisper") and _have_whisper():
            need = max(need, sysinfo.NEED_WHISPER.get(args.whisper_model, 2.2))
        ok, note = sysinfo.check(need)
        if not ok:
            log(tr("NOTE: ", "ВНИМАНИЕ: ") + note)
            log(tr("  If it crashes, see the advice at the end of the output.",
                "  Если упадёт — см. советы в конце вывода."))

        log(tr("Preparing the audio…", "Готовлю звук…"))
        work = AU.to_wav(args.audio, os.path.join(tmp, "source.wav"))
        dur = AU.duration(work)
        log(tr(f"Length: {int(dur//60)}:{int(dur%60):02d}",
           f"Длительность: {int(dur//60)}:{int(dur%60):02d}"))

        # Отчёт до тяжёлого: если текст не от этой песни или памяти не хватит,
        # лучше узнать сейчас, а не через десять минут.
        from kstudio import report as REP
        try:
            env, hop = AU.rms_envelope(work)
        except Exception:
            env, hop = [], 0.02
        rep = REP.build(args.audio, lyr, dur, env, hop,
                        model=args.whisper_model,
                        separate=not args.no_separate and S.available(),
                        whisper=args.align in ("auto", "whisper") and _have_whisper(),
                        language=args.lang)
        print()
        print(REP.as_text(rep))
        print()

        instrumental = vocals = None
        if not args.no_separate:
            instrumental, vocals = S.separate(work, os.path.join(tmp, "stems"),
                                              args.demucs_model, args.device, log)

        # по чистому вокалу разметка точнее, чем по полному миксу
        align_src = vocals or work

        if args.timings:
            log(tr(f"Taking the timings from {args.timings}", f"Беру тайминги из {args.timings}"))
            B.apply_timings(lyr, args.timings)
            engine = "json"
        else:
            lyr, engine = A.align(lyr, align_src, dur, args.align,
                                  args.whisper_model, args.lang, args.device, log)
        log(tr(f"Timing ready ({B.ENGINE_LABEL.get(engine, engine)}).",
           f"Разметка готова ({B.ENGINE_LABEL.get(engine, engine)})."))

        log(tr(f"Encoding the audio to {args.codec}…", f"Кодирую звук в {args.codec}…"))
        enc_dir = out_dir if args.no_embed else tmp
        base = os.path.splitext(os.path.basename(out_html))[0]
        tracks = {}
        if instrumental and vocals:
            tracks["instrumental"] = AU.encode(instrumental, os.path.join(enc_dir, base + "_минус"), args.codec)
            tracks["vocals"] = AU.encode(vocals, os.path.join(enc_dir, base + "_вокал"), args.codec)
        else:
            tracks["mix"] = AU.encode(work, os.path.join(enc_dir, base + "_аудио"), args.codec)

        log(tr("Building the HTML…", "Собираю HTML…"))
        B.build_html(out_html, lyr, dur, tracks, engine, embed=not args.no_embed,
                     title=args.title, artist=args.artist, ui_lang=args.ui_lang,
                     colors=[c.strip() for c in args.colors.split(",") if c.strip()],
                     theme=[c.strip() for c in args.theme.split(",") if c.strip()])

        if args.lrc:
            lrc = os.path.splitext(out_html)[0] + ".lrc"
            B.write_lrc(lrc, lyr)
            log(f"LRC: {lrc}")

        size = os.path.getsize(out_html)
        log(tr(f"Done: {out_html} ({human_size(size)})", f"Готово: {out_html} ({human_size(size)})"))
        if not (instrumental and vocals) and not args.no_separate:
            if S.available():
                print(tr("\nThe instrumental did not work out — the reason is in the Demucs "
                     "message above.",
                     "\nМинусовка не получилась — причина в сообщении Demucs выше."))
            else:
                print(tr("\nThere is no instrumental. To get one: pip install demucs",
                     "\nМинусовки нет. Чтобы её получить: pip install demucs"))

        if engine == "energy":
            # советовать установку имеет смысл, только если её и правда нет:
            # иначе подсказка врёт тому, кто просто выбрал быстрый движок
            print(tr("\nThe timing is approximate — it finds phrases by loudness "
                     "and often misses on a dense mix.",
                     "\nРазметка приблизительная — она ищет фразы по громкости и на "
                     "плотном миксе часто мажет."))
            if _have_whisper():
                print(tr("The stable-ts you already have gives word-by-word timing:"
                         "\n  · put “align = auto” in settings.ini"
                         "\n  · or run with --align whisper",
                         "Точную пословную разметку даст уже установленный stable-ts:"
                         "\n  · в settings.ini поставьте «движок = auto»"
                         "\n  · или запустите с ключом --align whisper"))
            else:
                print(tr("More accurate this way:  pip install stable-ts",
                         "Точнее будет так:  pip install stable-ts"))
            if args.no_separate:
                print(tr("An instrumental helps a lot too: the timing is then worked "
                         "out from the clean vocal, not from the whole song.",
                         "Ещё сильно помогает минусовка: разметка тогда считается по "
                         "чистому вокалу, а не по всей песне."))
            print(tr("Or fix it by hand right in the player: “Edit” → tap along.",
                     "Либо поправьте вручную прямо в плеере: «Правка» → разметка по тапам."))
        print(tr("\nOpen the file with a double click — no internet needed.",
                 "\nОткройте файл двойным щелчком — интернет не нужен."))
        return 0

    except (AU.AudioError, SystemExit) as e:
        from kstudio import sysinfo
        if sysinfo.is_memory_error(e):
            print("\n" + sysinfo.memory_advice(need if "need" in dir() else 4.0,
                                                sysinfo.available_gb()), file=sys.stderr)
            return 1
        print(tr(f"\nError: {e}", f"\nОшибка: {e}"), file=sys.stderr)
        return 1
    except (MemoryError, OSError) as e:
        from kstudio import sysinfo
        if sysinfo.is_memory_error(e):
            print("\n" + sysinfo.memory_advice(4.0, sysinfo.available_gb()), file=sys.stderr)
            return 1
        print(tr(f"\nError: {e}", f"\nОшибка: {e}"), file=sys.stderr)
        return 1
    except RuntimeError as e:
        # Внятные сообщения от движка показываем как есть: трассировка Python
        # пользователю ничего не объясняет.
        print(tr(f"\nIt did not work: {e}", f"\nНе получилось: {e}"), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print(tr("\nInterrupted.", "\nПрервано."), file=sys.stderr)
        return 130
    finally:
        if args.keep_temp:
            print(tr(f"Working folder: {tmp}", f"Рабочая папка: {tmp}"))
        else:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
