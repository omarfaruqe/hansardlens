"""Sort committee witnesses into kinds of organisation, from the title and organisation
printed with their name ("Assistant Deputy Minister, Tax Policy Branch, Department of
Finance").

Rules are keyword rules on the English label, checked in order; the first that matches
decides. They were written and checked against every witness label of the loaded
committees (methods note, section 11). A witness speaking "as an individual" is an
individual whatever else the label says. Anything with an organisation that no rule
recognises counts as a civil-society organisation (associations, charities, advocacy
groups, professional bodies), which is what most of them are.
"""

from __future__ import annotations

import re

from django.utils.translation import gettext_lazy as _

KINDS = {
    "federal": _("Federal departments and agencies"),
    "officer": _("Officers of Parliament and oversight offices"),
    "government": _("Provincial, territorial and municipal governments"),
    "indigenous": _("Indigenous governments and organisations"),
    "business": _("Businesses and industry associations"),
    "labour": _("Unions"),
    "research": _("Universities and think tanks"),
    "civil": _("Civil society organisations"),
    "international": _("International and foreign bodies"),
    "individual": _("Individuals"),
    "unknown": _("Not stated"),
}
ORDER = list(KINDS)
KIND_CHOICES = ORDER  # for the OpenAPI schema

PROVINCES = (
    r"ontario|quebec|québec|british columbia|alberta|saskatchewan|manitoba|nova scotia|"
    r"new brunswick|newfoundland|prince edward island|yukon|northwest territories|nunavut"
)


def _rx(*patterns: str) -> re.Pattern:
    return re.compile("|".join(f"(?:{p})" for p in patterns), re.I)


RULES: list[tuple[str, re.Pattern]] = [
    # Names that a later, broader rule would misread.
    (
        "federal",
        _rx(
            r"department of (?:indigenous services|crown-indigenous)",
            r"consulate general of canada",
            r"canada development investment corporation|public sector pension investment board",
            r"atomic energy of canada|defence investment agency",
        ),
    ),
    ("labour", _rx(r"union of [\w' ]+ employees")),
    ("research", _rx(r"engagement, universit")),
    (
        "government",
        _rx(rf"commissioner of (?:{PROVINCES})", rf"commissaire .* (?:{PROVINCES})"),
    ),
    (
        "business",
        _rx(
            r"national bank of canada",
            r"credit union|union des producteurs|microdistilleries",
            r"institute of steel construction|animal health institute|appraisal institute",
            r"institut de développement urbain",
        ),
    ),
    (
        "civil",
        _rx(
            r"union des consommateurs|civil liberties union|relations institute",
            r"food bank|accountability group|screen fund|action bénévole",
        ),
    ),
    (
        "officer",
        _rx(
            r"parliamentary budget officer",
            r"auditor general",
            r"commissioner of lobbying",
            r"conflict of interest and ethics commissioner",
            r"information commissioner",
            r"privacy commissioner",
            r"information and privacy commissioners of canada",
            r"procurement ombud",
            r"public sector integrity commissioner",
            r"commissioner of official languages",
            r"chief electoral officer|elections canada",
            r"senate ethics officer",
            r"parliamentary librar",
            r"office of the comptroller general(?!.*treasury)",
        ),
    ),
    (
        "international",
        _rx(
            r"\boecd\b|organisation for economic co-operation",
            r"international monetary fund|\bimf\b|world bank|united nations",
            r"embassy|consulate|high commission of",
            r"great lakes fishery commission|european centre of excellence",
            r"european (?:commission|union|parliament)",
            r"government of the united states|u\.s\. department|federal reserve",
        ),
    ),
    (
        "indigenous",
        _rx(
            r"first nations?\b",
            r"\binuit|\binuk\b|tapiriit",
            r"\bmétis|\bmetis",
            r"indigenous|aboriginal",
            r"friendship centres",
            r"\bcree\b|mohawk|anishinabek|haudenosaunee|wet'suwet'en|dene\b",
            r"tribal council|band council",
            r"native (?:women|child|friendship|council)",
            r"gi-ganawenima|tunngavik|\bnative\b|indian chiefs",
        ),
    ),
    (
        "government",
        _rx(
            rf"government of (?:the )?(?:{PROVINCES})",
            rf"province of (?:{PROVINCES})",
            r"gouvernement du québec",
            r"\bministry of\b",
            r"\bcity of\b|\btown of\b|\bville de\b|municipality|regional district|county of",
            r"federation of canadian municipalities|union des municipalités",
            r"fédération québécoise des municipalités",
            r"association of (?:municipalities|communities)",
            r"legislative assembly",
            rf"integrity commissioner of (?:{PROVINCES})",
            r"police service\b(?!s)|transit commission|sturgeon county",
            r"association of rural municipalities|municipalities (?:newfoundland|of)",
            r"municipalité|\bmrc\b|metro vancouver|translink|police services board",
            r"commissaire à l.éthique|commission d.accès à l.information",
            rf"registrar of lobbyists for (?:{PROVINCES})",
            r"ministère des finances du québec|finance québec",
        ),
    ),
    (
        "federal",
        _rx(
            r"\bdepartment of\b",
            r"treasury board",
            r"privy council office",
            r"bank of canada",
            r"\bcanada revenue agency|\bcanada border services agency",
            r"shared services canada|public services and procurement canada",
            r"statistics canada|service canada|parks canada|transport canada",
            r"health canada|public health agency|employment and social development canada",
            r"royal canadian mounted police|\brcmp\b",
            r"canadian security intelligence service|communications security establishment",
            r"office of the superintendent of financial institutions",
            r"financial consumer agency|fintrac|financial transactions and reports analysis",
            r"canada mortgage and housing corporation",
            r"canada post corporation",
            r"canada infrastructure bank|business development bank|export development canada",
            r"canada pension plan investment board",
            r"canadian commercial corporation|defence construction canada",
            r"house of commons|library of parliament|parliamentary protective service",
            r"canada school of public service|public service commission",
            r"canadian heritage|immigration, refugees and citizenship|global affairs canada",
            r"innovation, science and economic development|natural resources canada",
            r"environment and climate change canada|fisheries and oceans",
            r"indigenous services canada|crown-indigenous relations",
            r"canada economic development|economic development agency",
            r"canadian armed forces|national defence",
            r"department of justice|public prosecution service",
            r"canada energy regulator|canadian radio-television|crtc|competition bureau",
            r"canada council for the arts|canadian broadcasting corporation|cbc/radio-canada",
            r"canada deposit insurance corporation|farm credit canada|via rail|via hfr",
            r"canadian food inspection agency|canadian space agency|national research council",
            r"office of infrastructure of canada|infrastructure canada",
            r"federal housing advocate|canadian human rights commission",
            r"superintendent of bankruptcy|library and archives of canada",
            r"law clerk and parliamentary counsel|office of the prime minister",
            r"vaccine task force|atlantic canada opportunities agency",
            r"correctional service of canada|transportation safety board|"
            r"transportation accident investigation|governor general|"
            r"canadian institutes of health research|sustainable development technology canada|"
            r"port authority",
            r"veterans ombud|\bombudsman\b(?!.*(?:ontario|quebec|provincial))",
        ),
    ),
    (
        "labour",
        _rx(
            r"\bunions?\b|syndica|syndicat",
            r"labour congress|federation of labour|fédération des travailleurs",
            r"confédération des syndicats|centrale des syndicats",
            r"public service alliance|professional institute of the public service",
            r"building trades|unifor|teamsters|\bcupe\b|\bpsac\b",
            r"canadian teachers' federation|fédération autonome de l'enseignement",
            r"association of professional executives of the public service",
            r"canadian association of professional employees",
            r"nurses' (?:union|federation)|federation of nurses",
            r"workers of america|steelworkers|machinists",
            r"police federation|unite here|theatrical stage employees",
            r"alliance of canadian cinema, television and radio artists|\bactra\b",
            r"fédération nationale des communications|guilde des musiciens",
            r"postmasters and assistants|fish, food and allied workers",
            r"police association|millwright|association of justice counsel",
            r"faculty association|university teachers|construction trades",
        ),
    ),
    (
        "research",
        _rx(
            r"universit|université|\bcollege\b|collège|polytechnique",
            r"school of (?:public policy|business|management|economics|law)",
            r"\binstitute\b(?! of chartered)|institut\b",
            r"centre for policy alternatives|centre for future work|conference board",
            r"think tank|research (?:centre|center|institute|network)",
            r"chaire de|chair in\b|research chair",
            r"broadbent|fraser|c\.d\. howe|macdonald-laurier|iris\b",
            r"public policy forum|\bthe dais\b|analytics lab|école de technologie",
            r"tax accountability and research|higher education roundtable",
            r"hec montréal|governance innovation|carnegie endowment|norman paterson",
            r"observatory|samuelson-glushko",
        ),
    ),
    (
        "business",
        _rx(
            r"\binc\.?(?:\b|$)|\bltd\.?|\blimited\b|\bcorp\.?\b|\bcorporation\b|\bllp\b|"
            r"\bs\.e\.n\.c\.r\.l\.|\bplc\b|\bgmbh\b|\bco\.\b",
            r"chamber of commerce|chambres? de commerce|board of trade",
            r"federation of independent business",
            r"industr(?:y|ies) association|business council|manufacturers",
            r"producers(?:' )? association|bankers association|retail council",
            r"hotel association|home builders|mortgage professionals|credit union",
            r"council of canadian innovators|fintechs canada|news media canada",
            r"restaurants canada|insurance bureau|tourism industry",
            r"federation of agriculture|producteurs agricoles|farmers|fishermen|cattle",
            r"\bbank\b|\bbanque\b|capital|investments?\b|securities|insurance|assurance",
            r"\bgroup\b|\bgroupe\b|\bpartners\b|consulting|technologies|\btech\b|airlines?",
            r"industr(?:y|ie)|patronat|employers'? council|manufacturiers|exportateurs",
            r"petroleum|mining|prospectors|gas association|electricity|energy pipeline",
            r"renewable energy association|waterpower|helium|real estate|construction",
            r"contractors|airports?\b|railway|aviation|air transport|automobile dealers",
            r"forest products|producteurs|producers|growers|potato board|pork council",
            r"horticultural council|aquaculture|fisheries council|fish harvester|seafood",
            r"lobster council|wine|beer\b|cider|brewers|cannabis|food processors",
            r"tourism|touristique|tourisme|hospitality|restaurant|commerce de détail",
            r"agricultural producers|cattlemen|dairy|lait\b|érablières|ski\b",
            r"bitcoin|web3|digital asset|fintech|data and technology association|startup",
            r"supercluster|biotecanada|cosmetics alliance|electric mobility|live music",
            r"independent music|publishers|screen fund|automotive|trucking|shipping",
            r"scotiabank|deloitte|kpmg|pwc\b|ey law|fasken|wealthsimple|equifax|transunion",
            r"vancity|gofundme|mindgeek|dow canada|\bco\.$|developments\b|lending",
            r"gc strategies|everwind|markee|plato testing|inq law|baylis|providence therapeutics",
            r"public relations\b|management company|aircraft sales|javaroma|churchill wild",
            r"coach atlantic|bear head|world energy|oneclose|consolidated credit|tahinis",
            r"invest ottawa|edmonton global|platform calgary|centreport|aéro montréal",
            r"industrial|chambers of commerce|independent grocers|aluminium association",
            r"council of employers|duty free|produce marketing|ferry association",
            r"food and beverage canada|health food association|rail shippers|hôtellerie",
            r"\bbia\b|oilfield|fabricare|life underwriting|travel advisors|crop innovations",
            r"wheat development|importers and exporters|major mail users|technation",
            r"pathways alliance|pulse canada|nuclear association|aia canada|econext",
            r"michelin|globe and mail|mckinsey|amazon|google|microsoft|tiktok|uber canada",
            r"fincantieri|leonardo|shipyards|medline|h&r block|hitachi|borealis ai|bluedot",
            r"glacier media|ocean choice|spirits|distiller|wuxly|mre canada|gcstrategies",
            r"speakers' spotlight|\bfti\b|canadian football league|haider-moranis",
        ),
    ),
]


TITLE_ONLY = re.compile(
    r"(?:(?:and|chief|senior|national|deputy|vice|executive|general|technical|quebec|"
    r"founder|president|board|research|global|head|of|policy)\s+){0,4}"
    r"(?:president|director|officer|founder|representative|chair|executive|manager|advisor|"
    r"adviser|economist|counsel|partner|member|fellow|director general|development)"
    r"(?:\s+of\s+education)?|research department"
    r"|canada|tax|public affairs and communications|development and conception|"
    r"global head of policy development|privacy public policy for the americas|"
    r"public policy and government affairs(?:, canada)?",
    re.I,
)
INDIVIDUAL = _rx(r"\bas (?:an )?individual\b|à titre personnel")


def classify(detail: str, as_individual: bool = False) -> str:
    """The kind of witness for one label: title, then organisation (English)."""
    detail = (detail or "").strip()
    title, _, organisation = detail.partition(",")
    return classify_parts(title, organisation if organisation else detail, as_individual)


def classify_parts(title: str, organisation: str, as_individual: bool = False) -> str:
    """The kind of witness from a title and an organisation stored separately."""
    title, organisation = (title or "").strip(), (organisation or "").strip()
    if as_individual or INDIVIDUAL.search(f"{title}, {organisation}"):
        return "individual"
    if not organisation or TITLE_ONLY.fullmatch(organisation):
        return "unknown"
    for kind, rx in RULES:
        if rx.search(organisation):
            return kind
    return "civil"
