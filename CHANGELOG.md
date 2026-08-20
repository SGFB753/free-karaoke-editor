# What changed

Newest first. Each entry says what was wrong and what it means for you — the
commits themselves are one click away in the history.

*По-русски: [CHANGELOG.ru.md](CHANGELOG.ru.md)*

---

## 4.28.0

**A song from a link.** Under the field for the song file there is now a field
for a link: paste one, press “Take the sound”, and the audio is pulled out of
the video and put where a dropped file goes. The work is done by `yt-dlp` —
a few megabytes, no neural nets, offered by the setup as step six. Without it
the window says so before a link is pasted, and choosing a file still works.
When a download fails — a private video, a dead link, nothing at that address
— what the downloader itself said is shown, and the field stays open for
another link.

**And the words to go with it.** Once the sound is here, the lyrics are looked
for by the name of the song on [LRCLIB](https://lrclib.net), an open library
that needs neither key nor account. What comes back is a suggestion and is
treated as one: each says who sings it, how many lines it has and where it came
from, and it lands in a box to be read first. A wrong text lays wrong lines
over the whole song, so nothing is ever taken silently.

**How to update, in writing.** Taking the repository with `git clone` was
mentioned as a way past the macOS refusal, and there it stopped: nothing said
what an update does to the songs already made, so nobody had a reason to trust
`git pull` with them. All three documents now say it — one command, and
`projects/` and `app/settings.ini` are outside the repository and are not
touched — along with how to carry songs over from a folder that came from a
ZIP, and what to do when a pull refuses because a file was edited.

**The lyrics now have three ways in.** A file, as before; a text that was found;
or the words pasted into the window by hand — typed, corrected, taken from
anywhere. Pasted text is written into `projects/_incoming` as a `.txt`, so
everything downstream treats it exactly like a file of your own.

**A job that fell over let you out.** The progress screen had one way to end
badly: it kept spinning, with no “← To the list”. The job's own error came back
through the reader that treats an error as a broken request, which stopped the
polling on the very answer that had to be shown. Now the failure is named, the
reason stays in the log, and the way back is there.

---

## 4.27.1

**A licence.** [LICENSE](LICENSE) — MIT. Without one, an open repository says
“all rights reserved” by default, whatever the README promises.

**Your settings are yours.** `app/settings.ini` has left the repository:
`app/settings.example.ini` is the documented reference, and the first run of
`Install.bat` / `install.command` makes your copy from it. An update can no
longer overwrite what you chose, and with no settings file at all the program
uses its defaults.

**A dozen lines dumped at one instant, and the karaoke leapt through half the
lyrics.** On a quiet intro or a whispered verse Whisper finds nothing to hold on
to and returns a whole stretch of text at the single moment where it did hear
something — seven lines inside a fifth of a second. The program now sees such a
pile and spreads it out, at a sung pace, against the line that follows it. It
does not fill the whole gap: a gap may hold a breath, an intro or humming, and
covering that with lyrics claims as singing what is not sung. Lines that are
timed right are never touched, and a pile with nowhere to go — when the
neighbouring lines contradict each other — is left alone and named in the log:
which lines, at what second, and what to do about them.

**What the aligner mutters now lands in the log.** stable-ts says the single
most useful thing it has to say — “12/34 segments failed to align” — through a
Python warning, into a console window nobody is watching. It is now written to
the job log along with what it means: that many lines got no timing of their own
and will come out piled in one spot.

**An error no longer flashes past.** When a job falls over, the whole traceback
is written to `projects/last-error.txt` with the time, and the log says where it
is. One line of it was always shown; the rest used to scroll away.

**macOS refuses the first double-click, and the documentation now says why.**
A file that came from the internet carries a mark, and `studio.command` is not
signed by a paid Apple developer account — so the first attempt to open it is
answered with “the file cannot be checked for malware”. Nothing was scanned and
nothing was found, but it reads like a virus report, and there was not a word
about it in the README. Now all three documents a newcomer opens carry the
three ways through: starting it from the Terminal, letting the file through in
Privacy & Security, or taking the mark off the folder with `xattr`. Taking the
repository with `git clone` instead of a ZIP avoids the whole thing.

**The setup on macOS stopped after every single step.** `install.command`
installs ffmpeg with pip and then, in the same breath, asks Python whether it is
there. On macOS pip puts the package into the user's own site-packages — a
folder that often did not exist when the window opened, so it is not on the
search path and what was installed a second ago is invisible. The setup decided
the install had failed and gave up; the next step was reachable only by starting
the whole thing again, and then the same thing happened there. Each package is
now checked by a fresh Python, which reads the folders as they are now, and the
search path is refreshed after every install. On Windows nothing changed —
there pip writes where the program is already looking.

**One unfinished step no longer ends the setup.** Whatever could not be done is
named once at the end, and the steps below it — down to making your
`settings.ini` — run anyway. The advice now fits the machine it is printed on:
macOS used to be told `winget install Gyan.FFmpeg`, a command that exists only
on Windows, and the closing lines pointed at `.bat` files that a Mac cannot
open.

**Words with no audio under them are no longer laid over wordless singing.**
When a piled-up run repeats, word for word, a block of lines that IS timed, the
program leaves it where it is instead of spreading it: there is a reason no
audio was found for it, and a stretch of humming or vocalise is not a place to
paint lyrics over. Which of the two reasons it is, is told apart by the rest of
the song — either the lyrics file holds one repetition more than is sung, or the
aligner locked onto the wrong repetition and the whole timing is out by a pass.
Both are named in the log, with what to do about them.

**A stretch of song with no lyrics under it is now reported.** If the text ends
at 1:50 while the singing goes on to 2:50, the alignment did not stumble on a
line, it lost its place — and the log says so, along with the way out: re-time
with the loudness engine, which spreads the lines over the whole song.

**A song in another language kept the language of the previous one.**
The window remembered the language picked last time and used it for the next
song. If you had ever chosen “русский” by hand, an English text was handed to
Whisper as Russian — and the timing came out badly split, with no hint as to
why. Now every song starts from **“detect from the text”**; a choice made for
one song no longer decides the next. Re-timing (“Time it again”) reads the
language off the text too, instead of a remembered one.

**The report warns when the alphabet does not match.** If you do pick a
language by hand and the lyrics are not even written in its alphabet, the
report says so before the long part starts: *“The lyrics are not written in the
alphabet of the chosen language (русский). They look like english.”* Telling
alphabets apart is never a guess, so this never cries wolf about a genuinely
mixed text.

**English words are split into syllables properly.** Word length is what
spreads the time inside a line, and three endings used to lie: “lit-tle” and
“peo-ple” counted as one syllable, “walked” and “danced” as two, “makes” as
two. An English verse now lands much closer to how it is actually sung.

## 4.27.0 — first public version

The program as published: the Studio window, the standalone HTML page, the MP4
render, two voices, your own instrumental, the container, and the checks.

Fixed on the way to publishing:

- **The voice did not match a backing track of your own.** An official
  instrumental is mastered differently from the one under the vocal, so
  subtracting it with a single volume level left part of the arrangement in the
  “voice”. It is now subtracted per frequency band, over the spans without
  singing.
- **Both voices came out the same colour in the finished MP4** — the render
  used hard-coded colours instead of the ones from the page.
- **Pasted lines replaced the target instead of being inserted.** Now they are
  always inserted below the selection, and nothing is overwritten.
- **Several lines could not be selected at all** — dragging, Shift+click and
  Ctrl+click did nothing. Selection marks also vanished whenever the timeline
  was rebuilt.
- **Cyrillic names in file paths.** Song folders and finished files are named in
  Latin letters now (“Мамины Усы” → `maminy-usy`), so they open the same way on
  any system.
- **Nothing showed during the intro and the long interludes** — the slider moved
  and the screen stayed empty. A countdown to the next line now runs at the top,
  both in the Studio and in the video. Short pauses are not counted.
- **No report before the long part**, and none before the video render either.
- **Small type** everywhere: sizes are now in `rem` with `clamp`, so labels grow
  with the window and stay readable on a big screen.
- **A silent skip of the browser checks looked green.** With
  `KARAOKE_REQUIRE_BROWSER=1` it is a failure — the point of running them on a
  server is running them all.

## The language of the program

Published in English: the window, the finished page, the messages, the
documentation, the comments in the code and the checks. Russian is a switch in
the header (RU / EN) and [README.ru.md](README.ru.md); any other language is a
file in `app/kstudio/messages/`, with no code to edit.

## Checks

Every push runs the whole suite on a clean Ubuntu — see
[tests.yml](.github/workflows/tests.yml). Two differences from a working machine
were caught the hard way and are now covered: a runner has **no neural nets
installed** and an **empty model cache**, and the checks must be honest in both
worlds.
