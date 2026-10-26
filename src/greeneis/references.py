"""The one registry of sources the project cites.

Every citation on the Study, analysis and Overall Findings pages is a key into `REFERENCES`; the
References page is generated from the same list, so a title, year or link is written once. Each entry says
how far it has been checked (`verification`), because the project reference document (ref, section 11)
retrieved many sources as abstracts only.

Verification levels, strongest first:

- ``read_original``: the project read the original document (CSTEP 2018, CEEW 2018, CEA v20.0 Table S, the
  ASI 2023-24 layout documents).
- ``metadata_verified``: title, authors, year and DOI or page were confirmed against the publisher or
  Crossref on 2026-10-26; the full text was not read here.
- ``abstract_only``: the reference document retrieved an abstract, summary page or extract; details are
  quoted through it.
- ``unverified``: authors, year or exact title are not established; check before citing in the paper
  (TODO(verify), see docs/VERIFY.md).

Nothing here is invented: where a field is not known it is left empty and the entry says so.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

VERIFICATION: Final = {
    "read_original": "Read in the original",
    "metadata_verified": "Metadata verified, full text not read",
    "abstract_only": "Abstract or summary only",
    "unverified": "Unverified: check before citing",
}

CATEGORIES: Final = {
    "original": "Original studies that introduced the problem",
    "supporting": "Supporting studies and literature",
    "standards": "Reporting standards and guidance",
    "factors": "Emission-factor and dataset documentation",
    "methods": "Methodological references",
    "project": "Project documents",
    "software": "Software libraries",
}


@dataclass(frozen=True)
class Reference:
    key: str
    category: str
    authors: str  # "Surname, I., Surname, I." or the organisation; empty if not established
    year: str
    title: str
    venue: str  # journal, publisher or series, with volume and pages where known
    verification: str
    doi: str = ""
    url: str = ""
    ref_id: str = (
        ""  # the label in the project reference document's Source Register (ref section 11)
    )
    note: str = ""
    label: str = ""  # in-text name when authors or year are not established

    def __post_init__(self) -> None:
        if self.category not in CATEGORIES:
            raise ValueError(f"{self.key}: unknown category {self.category!r}")
        if self.verification not in VERIFICATION:
            raise ValueError(f"{self.key}: unknown verification {self.verification!r}")

    @property
    def link(self) -> str:
        return f"https://doi.org/{self.doi}" if self.doi else self.url

    @property
    def short(self) -> str:
        """In-text form: 'CSTEP (2018)', 'Weidema and Wesnaes (1996)' or 'Kuo et al. (2015)'."""
        if self.label:
            return self.label
        surnames = re.findall(r"([^,&]+?),\s*(?:[A-Z]\.[-\s]?)+", self.authors)
        if not surnames:
            who = self.authors or self.title
        elif len(surnames) == 1 and "et al" not in self.authors:
            who = surnames[0].strip()
        elif len(surnames) == 2 and "et al" not in self.authors:
            who = f"{surnames[0].strip()} and {surnames[1].strip()}"
        else:
            who = f"{surnames[0].strip()} et al."
        return f"{who} ({self.year})" if self.year else who


def citation(ref: Reference) -> str:
    """One consistent style: Authors (Year). Title. Venue. DOI or URL."""
    parts = []
    head = f"{ref.authors} ({ref.year})." if ref.authors and ref.year else None
    if head is None and ref.authors:
        head = f"{ref.authors} (year not established)."
    if head is None and ref.year:
        head = f"({ref.year})."
    if head:
        parts.append(head)
    parts.append(ref.title.rstrip(".") + ".")
    if ref.venue:
        parts.append(ref.venue.rstrip(".") + ".")
    if ref.link:
        parts.append(ref.link)
    return " ".join(parts)


_S1_URL = (
    "http://www.ghgplatform-india.org/Images/Publications/CSTEP_GHG_emission_Informal%20sector.pdf"
)
_S2_URL = (
    "https://www.ceew.in/sites/default/files/"
    "CEEW_GHG_Emissions_from_the_Informal_Sector_Policy_Brief_15May18.pdf"
)

REFERENCES: Final[tuple[Reference, ...]] = (
    # ---- original studies ------------------------------------------------------------------
    Reference(
        "cstep2018",
        "original",
        "Ananthakumar, M. R., & Roshna, N.",
        "2018",
        "Greenhouse Gas Emissions from the Informal Sector in India",
        "CSTEP, Bengaluru; supported by Shakti Sustainable Energy Foundation and GHG Platform India",
        "read_original",
        url=_S1_URL,
        ref_id="S1",
        label="CSTEP (2018)",
        note="Source of the fuel factors and calorific values in the factor library and of the 2015-16 "
        "estimate of 110 MtCO2e. Its Tables 7 and 8 are recomputed on the Gap 2 page.",
    ),
    Reference(
        "ceew2018",
        "original",
        "Biswas, T., Ganesan, K., & Gupta, V.",
        "2018",
        "Greenhouse Gases Emission Estimates for the Informal Manufacturing Industry of India",
        "CEEW Issue Brief, May 2018",
        "read_original",
        url=_S2_URL,
        ref_id="S2",
        label="CEEW (2018)",
        note="The publisher's web page returned HTTP 403 when re-checked on 2026-10-26; the PDF link is "
        "the one recorded in the reference document.",
    ),
    # ---- supporting studies ----------------------------------------------------------------
    Reference(
        "cstep2024",
        "supporting",
        "CSTEP",
        "2024",
        "Scope for deep decarbonisation in the MSME manufacturing sector (report page)",
        "CSTEP, 28 June 2024",
        "abstract_only",
        url="https://cstep.in/publication/scope-for-deep-decarbonisation-in-the-msme-manufacturing-sector/",
        ref_id="S5",
        note="Page title, date and the seven clusters were re-checked on 2026-10-26. The page does not "
        "state the number of units; the figure of 66 units comes from news coverage (energetica2024) via "
        "the reference document. The report PDF was not read.",
    ),
    Reference(
        "cstep_project",
        "supporting",
        "CSTEP",
        "",
        "Decarbonising and Scaling Clean Energy Solutions in India's MSME Manufacturing Sector "
        "(project page)",
        "CSTEP",
        "abstract_only",
        url="https://cstep.in/projects/decarbonising-and-scaling-clean-energy-solutions-in-indias-msme-manufacturing-sector/",
        ref_id="S4",
        note="Project page read in full by the reference document; it shows no publication date. Cited "
        "by the recommendation rules.",
    ),
    Reference(
        "energetica2024",
        "supporting",
        "Energetica India",
        "2024",
        "CSTEP Report Highlights Pathways for Decarbonising India's MSME Manufacturing Sector",
        "Energetica India, 6 July 2024 (news coverage of the CSTEP 2024 report)",
        "abstract_only",
        url="https://www.energetica-india.net/news/cstep-report-highlights-pathways-for-decarbonising-indias-msme-manufacturing-sector",
        ref_id="S7",
        note="Secondary source. Verify technology-specific figures against the CSTEP report.",
    ),
    Reference(
        "dte2022",
        "supporting",
        "Upadhyay, D.",
        "2022",
        "India's MSMEs must pare emissions and climate finance may be the nudge they need",
        "Down To Earth, 20 June 2022",
        "metadata_verified",
        url="https://www.downtoearth.org.in/energy/india-s-msmes-must-pare-emissions-and-climate-finance-may-be-the-nudge-they-need-83359",
        ref_id="S3",
        note="Headline, author and date re-checked on 2026-10-26. The credit-gap figures quoted in it are "
        "secondary and partly garbled in the reference document's copy; treat them as approximate.",
    ),
    Reference(
        "kuo2015",
        "supporting",
        "Kuo, T. C., Huang, M.-L., Hsu, C. W., Lin, C. J., Hsieh, C.-C., & Chu, C.-H.",
        "2015",
        "Application of data quality indicator of carbon footprint and water footprint",
        "International Journal of Precision Engineering and Manufacturing-Green Technology, 2(1), 43-50",
        "metadata_verified",
        doi="10.1007/s40684-015-0006-y",
        ref_id="S10",
        note="Authors, year and pages confirmed against Crossref on 2026-10-26.",
    ),
    Reference(
        "weidema1996",
        "supporting",
        "Weidema, B. P., & Wesnaes, M. S.",
        "1996",
        "Data quality management for life cycle inventories: an example of using data quality indicators",
        "Journal of Cleaner Production, 4(3-4), 167-174",
        "metadata_verified",
        doi="10.1016/S0959-6526(96)00043-1",
        note="Metadata confirmed against Crossref on 2026-10-26. Cited as the origin of the data-quality-"
        "indicator matrix that the pedigree-matrix approach builds on; not listed in the reference "
        "document's register.",
    ),
    Reference(
        "halat2026",
        "supporting",
        "Halat, K., Childe, S., Golding, N., & Summerscales, J.",
        "2026",
        "Scope 3 Carbon Emissions Assessment for Manufacturing SMEs",
        "Corporate Social Responsibility and Environmental Management, 33(5), 6302-6321",
        "metadata_verified",
        doi="10.1002/csr.70489",
        ref_id="S11",
        note="The reference document gives 'Childe et al.'; Crossref lists Halat as first author "
        "(V-14). Only the abstract was read.",
    ),
    Reference(
        "digital_reporting",
        "supporting",
        "",
        "",
        "Recommended Features for Digital Reporting Systems to Support Emissions Disclosures for Small "
        "and Medium-Sized Enterprises",
        "Conference chapter in Software Business in Digital Societies (TU Eindhoven research portal)",
        "unverified",
        url="https://research.tue.nl/en/publications/recommended-features-for-digital-reporting-systems-to-support-emi/",
        ref_id="S12",
        label="Digital reporting features for SMEs",
        note="Abstract only; authors and year were not shown in the retrieved text.",
    ),
    Reference(
        "ai_reporting",
        "supporting",
        "",
        "",
        "AI-Assisted Emission Reporting for Small and Medium-Sized Enterprises (SMEs)",
        "University of Technology Sydney repository",
        "unverified",
        url="https://opus.lib.uts.edu.au/rest/bitstreams/9d1aa619-e7a5-4763-bab3-5d7e6756f3c9/retrieve",
        ref_id="S13",
        label="AI-assisted SME emission reporting",
        note="Partial extract; authors and year were not shown in the retrieved text.",
    ),
    Reference(
        "srilanka2024",
        "supporting",
        "",
        "2024",
        "Carbon accounting in Sri Lankan SMEs: challenges and opportunities",
        "13th Annual International Research Conference (AiRC-2024), 27 November 2024",
        "abstract_only",
        url="https://dspace.lib.seu.ac.lk/items/c976c9ac-a82c-4d80-8e93-70a4ea059157",
        ref_id="S14",
        label="Sri Lankan SME carbon accounting (2024)",
        note="Abstract only; authors not recorded.",
    ),
    Reference(
        "t20_brief",
        "supporting",
        "",
        "",
        "Policy brief on automated carbon accounting for SMEs (T20 Brazil; exact title not established)",
        "SOAS repository",
        "unverified",
        url="https://eprints.soas.ac.uk/43486/1/T20Brazil.pdf",
        ref_id="S15",
        label="T20 Brazil brief",
        note="Fragmentary extract. The contract-loss claim attributed to it must be checked in the "
        "original before use.",
    ),
    Reference(
        "zocca2018",
        "supporting",
        "Zocca, R. O., Lima, T. M., et al.",
        "2018",
        "Computational tool to foster systematic thinking and sustainable environmental conscience in "
        "the selection of energy sources systems in agrifood companies",
        "Repository record (venue not established)",
        "unverified",
        url="https://ubibliorum.ubi.pt/entities/publication/94099ded-92e1-4a59-b68b-cfa9f6b7ef06",
        ref_id="S18",
        note="Abstract only; full author list and venue not shown. A Crossref title search on "
        "2026-10-26 did not find it.",
    ),
    Reference(
        "nist7850",
        "supporting",
        "NIST",
        "2012",
        "NIST Interagency Report 7850 (decision-guidance database "
        "system for sustainable manufacturing; exact title wording not established)",
        "NIST Interagency Report",
        "unverified",
        url="https://nvlpubs.nist.gov/nistpubs/ir/2012/NIST.IR.7850.pdf",
        ref_id="S19",
        note="Extract only; check the title in the original.",
    ),
    Reference(
        "helo2024",
        "supporting",
        "Helo, P., & Mayanti, B.",
        "2024",
        "Dynamics of energy costs and emissions in operations: analysing energy operational adjustment",
        "Conference paper (venue as recorded in the reference document)",
        "unverified",
        url="https://osuva.uwasa.fi/items/f697ba76-838f-44da-9713-444d4184fea7/full",
        ref_id="S20",
        note="Abstract only. A 2026 IEEE Engineering Management Review article by Helo, Mayanti and Mahmud "
        "(doi 10.1109/emr.2026.3709537) has a similar title; whether it is the same work was not "
        "established.",
    ),
    Reference(
        "neves2022",
        "supporting",
        "Neves-Silva, R., & Camarinha-Matos, L. M.",
        "2022",
        "Context-Based Decision Support System for Energy Efficiency in Industrial Plants",
        "Sustainability, 14(7), 3885",
        "metadata_verified",
        doi="10.3390/su14073885",
        ref_id="S21",
        note="Authors confirmed against Crossref on 2026-10-26 (the reference document had none). Only "
        "the abstract was read.",
    ),
    Reference(
        "ecovadis_estimator",
        "supporting",
        "ESG Post",
        "",
        "EcoVadis Carbon Estimator helps decarbonisation efforts across enterprises",
        "Trade press / vendor material",
        "unverified",
        url="https://esgpost.com/ecovadis-carbon-estimator-helps-decarbonisation-efforts-across-enterprises/",
        ref_id="S22",
        note="Marketing material. Illustrates that commercial SME tools exist; not evidence of "
        "effectiveness.",
    ),
    Reference(
        "persefoni_sme",
        "supporting",
        "Persefoni",
        "",
        "Carbon accounting for SMEs: misconceptions",
        "Vendor blog",
        "unverified",
        url="https://persefoni.com/blog/carbon-accounting-smes-misconceptions",
        ref_id="S22",
        note="Marketing material; same caveat as the EcoVadis entry.",
    ),
    # ---- standards and guidance -------------------------------------------------------------
    Reference(
        "ghgp_uncertainty",
        "standards",
        "GHG Protocol",
        "",
        "Quantitative Inventory Uncertainty (guidance on uncertainty assessment in GHG inventories)",
        "World Resources Institute and WBCSD",
        "abstract_only",
        url="https://ghgprotocol.org/sites/default/files/Quantitative%20Uncertainty%20Guidance.pdf",
        ref_id="S9",
        note="Extract only; the pedigree-matrix table in the full guidance has not been read. The trust "
        "values are not calibrated against it yet (CLAUDE.md rule 3). No publication year is recorded.",
    ),
    Reference(
        "ipcc2006",
        "standards",
        "IPCC",
        "2006",
        "2006 IPCC Guidelines for National Greenhouse Gas Inventories, Volume 2: Energy",
        "Institute for Global Environmental Strategies, Hayama",
        "unverified",
        url="https://www.ipcc-nggip.iges.or.jp/public/2006gl/vol2.html",
        note="Cited through CSTEP (2018), which follows it. The original was not read and no factor in "
        "the library is taken from it directly.",
    ),
    # ---- factor and dataset documentation ---------------------------------------------------
    Reference(
        "cea_v20",
        "factors",
        "Central Electricity Authority, Ministry of Power",
        "2024",
        "CO2 Baseline Database for the Indian Power Sector, User Guide, Version 20.0 (December 2024), "
        "Table S",
        "CEA, New Delhi",
        "read_original",
        url="https://cea.nic.in/wp-content/uploads/baseline/2025/07/User_Guide__ver_17_2021.pdf",
        ref_id="S16",
        label="CEA CO2 Baseline Database v20.0 (2024)",
        note="Grid factor 0.727 tCO2/MWh (average) and 0.757 (combined margin), FY 2023-24, read "
        "directly from Table S of v20.0 (V-01). The URL is the version-17 guide recorded in the "
        "reference document; the v20.0 URL was not recorded (TODO(verify)).",
    ),
    Reference(
        "asi2023",
        "factors",
        "Ministry of Statistics and Programme Implementation (MoSPI)",
        "2024",
        "Annual Survey of Industries, 2023-24, unit-level merged file (ASI24m.TXT) and Data Structure "
        "document",
        "MoSPI National Data Archive (microdata.gov.in)",
        "read_original",
        url="https://microdata.gov.in",
        label="MoSPI, ASI 2023-24",
        note="Public file, downloaded 2026-10-25. The data-structure document was used to read the "
        "layout. The portal's terms of use are unread (V-18, V-37), so only aggregate results are "
        "published. The catalogue page URL for the round was not recorded.",
    ),
    Reference(
        "sameeksha",
        "factors",
        "SAMEEKSHA (hosted by TERI)",
        "",
        "MSME cluster profiles and detailed project reports",
        "sameeeksha.org",
        "abstract_only",
        url="https://sameeeksha.org",
        note="Background on clusters only; no number on the site comes from these files (V-17).",
    ),
    # ---- methods ---------------------------------------------------------------------------
    Reference(
        "efron1979",
        "methods",
        "Efron, B.",
        "1979",
        "Bootstrap methods: another look at the jackknife",
        "The Annals of Statistics, 7(1), 1-26",
        "metadata_verified",
        doi="10.1214/aos/1176344552",
        note="Basis of the cluster bootstrap used for every confidence interval in the study.",
    ),
    Reference(
        "holm1979",
        "methods",
        "Holm, S.",
        "1979",
        "A simple sequentially rejective multiple test procedure",
        "Scandinavian Journal of Statistics, 6(2), 65-70",
        "unverified",
        url="https://www.jstor.org/stable/4615733",
        note="Used for the correction across H1-H5. Metadata was written from memory and a Crossref "
        "search on 2026-10-26 did not return it; check before citing.",
    ),
    # ---- project documents -----------------------------------------------------------------
    Reference(
        "refdoc",
        "project",
        "Owner of the project",
        "2026",
        "GreenEIS: Research and Design Reference (Table 5.1 gap analysis; Source Register, section 11)",
        "docs/reference/GreenEIS_Research_and_Design_Reference.docx",
        "read_original",
        label="Reference document (2026)",
        note="Source of the list of seven research gaps and of the labels S1-S22. It is a project "
        "document, not a published source.",
    ),
    Reference(
        "researchdesign",
        "project",
        "GreenEIS project",
        "2026",
        "Research design: question, hypotheses H1-H5, procedure, threats to validity",
        "docs/RESEARCH_DESIGN.md",
        "read_original",
    ),
    Reference(
        "results_asi",
        "project",
        "GreenEIS project",
        "2026",
        "Results of the pre-specified run on ASI 2023-24, with the declared sensitivity and textile cuts",
        "docs/RESULTS_ASI_2023-24.md and outputs/study_asi_2023-24*.json",
        "read_original",
    ),
    Reference(
        "verify",
        "project",
        "GreenEIS project",
        "2026",
        "Unverified-items register (V-01 to V-39)",
        "docs/VERIFY.md",
        "read_original",
    ),
    # ---- software --------------------------------------------------------------------------
    Reference(
        "streamlit",
        "software",
        "Streamlit Inc.",
        "",
        "Streamlit documentation",
        "streamlit.io",
        "metadata_verified",
        url="https://docs.streamlit.io",
    ),
    Reference(
        "plotly",
        "software",
        "Plotly Technologies Inc.",
        "",
        "Plotly Python graphing library",
        "plotly.com",
        "metadata_verified",
        url="https://plotly.com/python/",
    ),
    Reference(
        "pandas",
        "software",
        "The pandas development team",
        "",
        "pandas documentation",
        "pandas.pydata.org",
        "metadata_verified",
        url="https://pandas.pydata.org/docs/",
    ),
    Reference(
        "numpy",
        "software",
        "NumPy developers",
        "",
        "NumPy documentation",
        "numpy.org",
        "metadata_verified",
        url="https://numpy.org/doc/",
    ),
    Reference(
        "scipy",
        "software",
        "SciPy developers",
        "",
        "SciPy documentation",
        "scipy.org",
        "metadata_verified",
        url="https://docs.scipy.org/doc/scipy/",
    ),
    Reference(
        "statsmodels",
        "software",
        "statsmodels developers",
        "",
        "statsmodels documentation",
        "statsmodels.org",
        "metadata_verified",
        url="https://www.statsmodels.org/stable/",
    ),
)

SOFTWARE_PACKAGES: Final = {
    "streamlit": "streamlit",
    "plotly": "plotly",
    "pandas": "pandas",
    "numpy": "numpy",
    "scipy": "scipy",
    "statsmodels": "statsmodels",
}

_BY_KEY = {r.key: r for r in REFERENCES}


def get(key: str) -> Reference:
    """The reference with this key. Raises KeyError for an unknown key, so a typo cannot go unnoticed."""
    return _BY_KEY[key]


def by_ref_id(ref_id: str) -> Reference | None:
    """The reference carrying a reference-document label such as 'S7' (the first, if two share one)."""
    return next((r for r in REFERENCES if r.ref_id == ref_id), None)


def by_category() -> dict[str, list[Reference]]:
    return {cat: [r for r in REFERENCES if r.category == cat] for cat in CATEGORIES}


def anchor(key: str) -> str:
    """Page anchor of a reference on the References page."""
    return f"ref-{key}"
