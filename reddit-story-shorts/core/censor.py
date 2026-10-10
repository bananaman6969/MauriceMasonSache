"""Optional word censoring shared by text previews and video generation."""
import re
from dataclasses import replace
from difflib import SequenceMatcher

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

# English creator-style alternatives. Whole-word matching avoids changing
# ordinary words such as grape, cocktail, assignment, and analysis.
REPLACEMENTS.update({
    "damn": ("d*mn", "darn"), "damned": ("d*mned", "darned"),
    "goddamn": ("godd*mn", "goshdarn"), "goddamned": ("godd*mned", "goshdarned"),
    "dick": ("d*ck", "jerk"), "dicks": ("d*cks", "jerks"),
    "dickhead": ("d*ckhead", "jerk"), "dickheads": ("d*ckheads", "jerks"),
    "prick": ("pr*ck", "jerk"), "pricks": ("pr*cks", "jerks"),
    "cock": ("c*ck", "rooster"), "cocks": ("c*cks", "roosters"),
    "pussy": ("p*ssy", "kitty"), "pussies": ("p*ssies", "kitties"),
    "slut": ("sl*t", "person"), "sluts": ("sl*ts", "people"),
    "whore": ("wh*re", "person"), "whores": ("wh*res", "people"),
    "kill": ("unalive", "unalive"), "killed": ("unalived", "unalived"),
    "kills": ("unalives", "unalives"), "killing": ("unaliving", "unaliving"),
    "killer": ("unaliver", "unaliver"), "killers": ("unalivers", "unalivers"),
    "death": ("d*ath", "passing"), "deaths": ("d*aths", "passings"),
    "dead": ("unalive", "unalive"), "die": ("unalive", "unalive"),
    "died": ("unalived", "unalived"), "dying": ("unaliving", "unaliving"),
    "suicide": ("s*icide", "unaliving"), "suicidal": ("s*icidal", "distressed"),
    "homicide": ("h*micide", "unaliving"), "homicides": ("h*micides", "unalivings"),
    "stab": ("st*b", "poke"), "stabbed": ("st*bbed", "poked"),
    "stabbing": ("st*bbing", "poking"), "stabs": ("st*bs", "pokes"),
    "shoot": ("sh*ot", "pew"), "shooting": ("sh*oting", "pewing"),
    "shootings": ("sh*otings", "incidents"), "shooter": ("sh*oter", "attacker"),
    "shooters": ("sh*oters", "attackers"),
    "blood": ("bl*od", "red"), "bloody": ("bl*ody", "messy"),
    "gore": ("g*re", "graphic"), "torture": ("t*rture", "torment"),
    "tortured": ("t*rtured", "tormented"), "torturing": ("t*rturing", "tormenting"),
    "assault": ("ass*ult", "attack"), "assaulted": ("ass*ulted", "attacked"),
    "assaulting": ("ass*ulting", "attacking"), "assaults": ("ass*ults", "attacks"),
    "abuse": ("ab*se", "mistreatment"), "abused": ("ab*sed", "mistreated"),
    "abusing": ("ab*sing", "mistreating"), "abusive": ("ab*sive", "harmful"),
    "abuser": ("ab*ser", "aggressor"), "abusers": ("ab*sers", "aggressors"),
    "molest": ("mol*st", "harm"), "molested": ("mol*sted", "harmed"),
    "molesting": ("mol*sting", "harming"), "molestation": ("mol*station", "harm"),
    "sex": ("s*x", "intimacy"), "sexual": ("s*xual", "intimate"),
    "sexually": ("s*xually", "intimately"), "sexy": ("s*xy", "attractive"),
    "porn": ("p*rn", "corn"), "porno": ("p*rno", "corn"),
    "pornography": ("p*rnography", "cornography"), "pornographic": ("p*rnographic", "cornographic"),
    "nude": ("n*de", "unclothed"), "nudes": ("n*des", "pictures"),
    "naked": ("n*ked", "unclothed"), "nudity": ("n*dity", "exposure"),
    "penis": ("p*nis", "anatomy"), "vagina": ("v*gina", "anatomy"),
    "orgasm": ("org*sm", "climax"), "orgasms": ("org*sms", "climaxes"),
    "masturbate": ("mast*rbate", "selfpleasure"), "masturbating": ("mast*rbating", "selfpleasuring"),
    "masturbation": ("mast*rbation", "selfpleasure"),
    "drug": ("dr*g", "substance"), "drugs": ("dr*gs", "substances"),
    "cocaine": ("c*caine", "snow"), "heroin": ("h*roin", "substance"),
    "meth": ("m*th", "crystals"), "methamphetamine": ("m*thamphetamine", "crystals"),
    "fentanyl": ("f*ntanyl", "substance"), "overdose": ("overd*se", "overconsumption"),
    "overdosed": ("overd*sed", "overconsumed"), "overdosing": ("overd*sing", "overconsuming"),
})
WORD_PATTERN = re.compile(r"\b(?:" + "|".join(re.escape(word) for word in sorted(REPLACEMENTS, key=len, reverse=True)) + r")\b", re.I)
# Keep contractions and hyphenated words intact when comparing speech boundaries.
TOKEN_PATTERN = re.compile(r"[\w*]+(?:['’\-][\w*]+)*[.,!?;:]?")


def normalized_word(word):
    return re.sub(r"[^\w*]", "", word).lower()


def censor_text(text: str) -> str:
    """Return masked captions and creator-style euphemisms for the editor."""
    return WORD_PATTERN.sub(lambda match: REPLACEMENTS[match.group().lower()][0], text)


def narration_text(display_text: str) -> str:
    """Give speech a pronounceable version instead of asking it to read stars."""
    masked = {display: speech for display, speech in REPLACEMENTS.values() if "*" in display}
    pattern = r"(?<!\w)(?:" + "|".join(re.escape(word) for word in sorted(masked, key=len, reverse=True)) + r")(?!\w)"
    return re.sub(pattern, lambda match: masked[match.group().lower()], display_text, flags=re.I)


def caption_words(words, display_text, spoken_text=None):
    """Restore display spelling and punctuation using the actual speech timestamps."""
    display = TOKEN_PATTERN.findall(display_text)
    spoken = [normalized_word(token) for token in TOKEN_PATTERN.findall(
        narration_text(display_text) if spoken_text is None else spoken_text)]
    observed = [normalized_word(word.word) for word in words]
    result = list(words)
    for block in SequenceMatcher(a=spoken, b=observed, autojunk=False).get_matching_blocks():
        for offset in range(block.size):
            target = display[block.a + offset]
            if "*" in target or target.endswith((".", ",", "!", "?", ";", ":")):
                index = block.b + offset
                result[index] = replace(words[index], word=target)
    return result


def prepare_story(title: str, body: str, enabled: bool):
    return (censor_text(title), censor_text(body)) if enabled else (title, body)
