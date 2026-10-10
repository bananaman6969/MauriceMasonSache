"""Optional word censoring shared by text previews and video generation."""
import re
from dataclasses import replace
from difflib import SequenceMatcher

# Whole words and common inflections only: never censor substrings such as grape.
WORD_PATTERN = re.compile(
    r"\b(?:rape|raped|rapes|raping|rapist|rapists|"
    r"murder|murders|murdered|murdering|murderer|murderers|"
    r"fuck|fucks|fucked|fucking|fucker|fuckers|motherfucker|motherfuckers|"
    r"shit|shits|shitty|bullshit|bitch|bitches|bastard|bastards|"
    r"asshole|assholes|cunt|cunts)\b", re.IGNORECASE,
)


REPLACEMENTS = {
    "rape": ("gr*pe", "grape"), "raped": ("gr*ped", "graped"),
    "rapes": ("gr*pes", "grapes"), "raping": ("gr*ping", "graping"),
    "rapist": ("gr*pist", "grapist"), "rapists": ("gr*pists", "grapists"),
    "murder": ("unaliving", "unaliving"), "murders": ("unalivings", "unalivings"),
    "murdered": ("unalived", "unalived"), "murdering": ("unaliving", "unaliving"),
    "murderer": ("unaliver", "unaliver"), "murderers": ("unalivers", "unalivers"),
    "fuck": ("f*ck", "eff"), "fucks": ("f*cks", "effs"),
    "fucked": ("f*cked", "effed"), "fucking": ("f*cking", "effing"),
    "fucker": ("f*cker", "effer"), "fuckers": ("f*ckers", "effers"),
    "motherfucker": ("motherf*cker", "motherfluffer"), "motherfuckers": ("motherf*ckers", "motherfluffers"),
    "shit": ("sh*t", "shoot"), "shits": ("sh*ts", "shoots"), "shitty": ("sh*tty", "cruddy"),
    "bullshit": ("bullsh*t", "bullcrap"), "bitch": ("b*tch", "beach"), "bitches": ("b*tches", "beaches"),
    "bastard": ("b*stard", "jerk"), "bastards": ("b*stards", "jerks"),
    "asshole": ("a**hole", "jerk"), "assholes": ("a**holes", "jerks"),
    "cunt": ("c*nt", "jerk"), "cunts": ("c*nts", "jerks"),
}


def censor_text(text: str) -> str:
    """Return masked captions and creator-style euphemisms for the editor."""
    return WORD_PATTERN.sub(lambda match: REPLACEMENTS[match.group().lower()][0], text)


def narration_text(display_text: str) -> str:
    """Give speech a pronounceable version instead of asking it to read stars."""
    masked = {display: speech for display, speech in REPLACEMENTS.values() if "*" in display}
    pattern = r"(?<!\w)(?:" + "|".join(re.escape(word) for word in sorted(masked, key=len, reverse=True)) + r")(?!\w)"
    return re.sub(pattern, lambda match: masked[match.group().lower()], display_text, flags=re.I)


def caption_words(words, display_text):
    """Restore masked spellings at aligned word positions without changing timings."""
    display = re.findall(r"[\w*]+", display_text)
    spoken = re.findall(r"[\w*]+", narration_text(display_text).lower())
    observed = [re.sub(r"[^\w*]", "", word.word).lower() for word in words]
    result = list(words)
    for block in SequenceMatcher(a=spoken, b=observed, autojunk=False).get_matching_blocks():
        for offset in range(block.size):
            target = display[block.a + offset]
            if "*" in target:
                index = block.b + offset
                result[index] = replace(words[index], word=target)
    return result


def prepare_story(title: str, body: str, enabled: bool):
    return (censor_text(title), censor_text(body)) if enabled else (title, body)
