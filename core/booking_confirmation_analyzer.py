import re
import unicodedata
from difflib import SequenceMatcher


class BookingConfirmationAnalyzer:
    """
    Carrier-agnostic, text-first Booking Confirmation parser.

    Design goals:
    - Never depend on page coordinates or one carrier's form.
    - Accept common aliases, abbreviations, punctuation, and line breaks.
    - Read label/value on the same line OR value on following lines.
    - Use context to classify ETD / ETA / POL ETA and deadlines.
    - Preserve unknown deadline-like fields in Other Deadlines instead of
      silently dropping them.

    The parser intentionally keeps the original text values rather than
    converting dates/times, because shipping documents use many local formats
    and the user should see exactly what the carrier issued.
    """

    FIELD_ALIASES = {
        "carrier_booking_no": [
            "BOOKING NO",
            "BOOKING NUMBER",
            "BOOKING #",
            "BOOKING REF",
            "BOOKING REFERENCE",
            "BOOKING ID",
            "BKG NO",
            "BKG NUMBER",
            "BKG #",
            "BKG REF",
            "BK NO",
            "CARRIER BOOKING NO",
            "CARRIER BOOKING NUMBER",
            "RESERVATION NO",
            "RESERVATION NUMBER",
            "RESERVATION REF",
        ],
        "application_no": [
            "APPLICATION NO",
            "APPLICATION NUMBER",
            "APPLICATION #",
            "APP NO",
            "APP NUMBER",
            "REQUEST NO",
            "REQUEST NUMBER",
        ],
        "vessel_voyage": [
            "VESSEL/VOYAGE",
            "VESSEL / VOYAGE",
            "VESSEL & VOYAGE",
            "VESSEL AND VOYAGE",
            "VESSEL VOYAGE",
            "VESSEL/VOY",
            "VESSEL / VOY",
            "VSL/VOY",
            "VSL / VOY",
            "VESSEL VOYAGE NO",
            "VESSEL/VOYAGE NO",
            "VESSEL NAME/VOYAGE",
        ],
        "carrier": [
            "CARRIER",
            "OCEAN CARRIER",
            "SHIPPING LINE",
            "CARRIER NAME",
            "LINER",
            "STEAMSHIP LINE",
        ],
        "on_behalf_of": [
            "ON BEHALF OF",
            "ISSUED ON BEHALF OF",
            "REPRESENTING",
        ],
        "port_of_receipt": [
            "PORT OF RECEIPT",
            "PLACE OF RECEIPT",
            "RECEIPT PLACE",
            "RECEIPT PORT",
            "POR",
        ],
        "port_of_loading": [
            "PORT OF LOADING",
            "PORT OF LOAD",
            "LOADING PORT",
            "LOAD PORT",
            "ORIGIN PORT",
            "PORT OF ORIGIN",
            "DEPARTURE PORT",
            "POL",
        ],
        "pol_terminal": [
            "ESTIMATED POL CALLING TERMINAL",
            "POL CALLING TERMINAL",
            "POL TERMINAL",
            "LOADING TERMINAL",
            "LOAD TERMINAL",
            "TERMINAL AT POL",
            "DEPARTURE TERMINAL",
            "EXPORT TERMINAL",
            "CY TERMINAL",
        ],
        "port_of_discharge": [
            "PORT OF DISCHARGE",
            "DISCHARGE PORT",
            "PORT OF DISCH",
            "DISCH PORT",
            "DESTINATION PORT",
            "PORT OF DESTINATION",
            "ARRIVAL PORT",
            "POD",
        ],
        "final_destination": [
            "FINAL DESTINATION",
            "PLACE OF DELIVERY",
            "DELIVERY PLACE",
            "FINAL PLACE OF DELIVERY",
            "DESTINATION",
        ],
        "service_type_mode": [
            "SERVICE TYPE/MODE",
            "SERVICE TYPE / MODE",
            "SERVICE TYPE",
            "SERVICE MODE",
            "MODE OF SERVICE",
            "SERVICE",
        ],
        "stuffing_place": [
            "STUFFING PLACE",
            "STUFFING LOCATION",
            "PLACE OF STUFFING",
            "STUFFING AT",
            "CARGO STUFFING PLACE",
        ],
        "commodity": [
            "COMMODITY",
            "COMMODITY DESCRIPTION",
            "CARGO DESCRIPTION",
            "DESCRIPTION OF GOODS",
            "GOODS DESCRIPTION",
            "CARGO",
        ],
        "shipper": [
            "SHIPPER",
            "SHIPPER NAME",
            "EXPORTER",
            "BOOKING PARTY",
        ],
        "empty_pick_up_at": [
            "EMPTY PICK UP AT",
            "EMPTY PICKUP AT",
            "EMPTY PICK-UP AT",
            "EMPTY PICK UP",
            "EMPTY PICKUP",
            "EMPTY RELEASE DEPOT",
            "EMPTY PICKUP DEPOT",
            "EMPTY DEPOT",
            "PICK UP EMPTY AT",
        ],
        "inland_return_to": [
            "INLAND RETURN TO",
            "EMPTY RETURN TO",
            "EMPTY RETURN DEPOT",
            "RETURN EMPTY TO",
            "FULL RETURN TO",
            "LADEN RETURN TO",
            "RETURN DEPOT",
        ],
        "service_contract": [
            "SERVICE CONTRACT",
            "SERVICE CONTRACT NO",
            "CONTRACT NO",
            "CONTRACT NUMBER",
            "SVC CONTRACT",
            "SVC CONTRACT NO",
            "SC NO",
        ],
        "payment_term": [
            "PAYMENT TERM",
            "PAYMENT TERMS",
            "FREIGHT TERM",
            "FREIGHT TERMS",
            "FREIGHT PAYMENT",
            "PAYMENT",
        ],
    }

    # Ambiguous short aliases need field-specific guards.
    # A generic token such as "CARRIER" must not match
    # "CARRIER BOOKING NO", and "CARGO" must not match
    # "CARGO CLOSING".
    FIELD_LABEL_FORBIDDEN_TERMS = {
        "carrier": [
            "BOOKING",
            "BOOKING NO",
            "BOOKING NUMBER",
            "BOOKING REF",
            "BOOKING REFERENCE",
            "CONFIRMATION",
            "RESERVATION",
            "REFERENCE",
            "REF",
        ],
        "final_destination": [
            "ETA",
            "ARRIVAL",
            "CUT OFF",
            "CUTOFF",
            "CUT-OFF",
            "DEADLINE",
            "CLOSING",
        ],
        "service_type_mode": [
            "CONTRACT",
            "AGREEMENT",
            "RATE",
            "TARIFF",
        ],
        "commodity": [
            "CLOSING",
            "CUT OFF",
            "CUTOFF",
            "CUT-OFF",
            "DEADLINE",
            "RECEIVING",
        ],
        "port_of_loading": [
            "ETA",
            "ETD",
            "ARRIVAL",
            "DEPARTURE",
            "TERMINAL",
            "CUT OFF",
            "CUTOFF",
            "CUT-OFF",
            "DEADLINE",
            "CLOSING",
        ],
        "port_of_discharge": [
            "ETA",
            "ETD",
            "ARRIVAL",
            "DEPARTURE",
            "TERMINAL",
            "CUT OFF",
            "CUTOFF",
            "CUT-OFF",
            "DEADLINE",
            "CLOSING",
        ],
    }

    # Single-label fields that may appear separately instead of VESSEL/VOYAGE.
    VESSEL_ALIASES = [
        "VESSEL",
        "VESSEL NAME",
        "VSL",
        "MOTHER VESSEL",
        "OCEAN VESSEL",
        "FEEDER VESSEL",
        "VSL NAME",
        "M/V",
        "MV",
    ]

    VOYAGE_ALIASES = [
        "VOYAGE",
        "VOYAGE NO",
        "VOYAGE NUMBER",
        "VOY NO",
        "VOY",
        "VOYAGE #",
        "VYG",
        "VYG NO",
        "VYG NUMBER",
    ]

    DEADLINE_ALIASES = {
        "cy_cutoff": [
            "CY CUT OFF",
            "CY CUTOFF",
            "CY CUT-OFF",
            "CY CLOSING",
            "CY CLOSING TIME",
            "CY CLOSING DATE",
            "CARGO CUT OFF",
            "CARGO CUTOFF",
            "CARGO CUT-OFF",
            "CARGO CLOSING",
            "CARGO CLOSING TIME",
            "CONTAINER CUT OFF",
            "CONTAINER CUTOFF",
            "CONTAINER CUT-OFF",
            "CONTAINER CLOSING",
            "TERMINAL CUT OFF",
            "TERMINAL CUTOFF",
            "TERMINAL CLOSING",
            "GATE IN CUT OFF",
            "GATE-IN CUT OFF",
            "GATE IN CUTOFF",
            "GATE IN DEADLINE",
            "GATE-IN DEADLINE",
            "FULL CONTAINER CUT OFF",
            "FULL CONTAINER CUTOFF",
            "FULL CONTAINER DELIVERY CUT OFF",
            "FCL CUT OFF",
            "FCL CUTOFF",
            "PORT CUT OFF",
            "PORT CUTOFF",
            "PORT CLOSING",
            "LADEN CUT OFF",
            "LADEN CUTOFF",
            "LADEN RETURN CUT OFF",
            "LADEN RETURN DEADLINE",
            "EXPORT CARGO CLOSING",
            "CUTOFF DATE TIME",
            "CUT OFF DATE TIME",
            "CUT OFF DATE / TIME",
            "CUT OFF DATE/TIME",
            "CUT-OFF DATE/TIME",
            "CUT OFF TIME",
            "CUTOFF TIME",
        ],
        "vgm_cutoff": [
            "VGM CUT OFF",
            "VGM CUTOFF",
            "VGM CUT-OFF",
            "VGM CUT OFF DATE",
            "VGM CUT OFF TIME",
            "VGM DEADLINE",
            "VGM CLOSING",
            "VGM SUBMISSION CUT OFF",
            "VGM SUBMISSION CUTOFF",
            "VGM SUBMISSION DEADLINE",
            "VERIFIED GROSS MASS CUT OFF",
            "VERIFIED GROSS MASS CUTOFF",
            "VERIFIED GROSS MASS DEADLINE",
        ],
        "si_cutoff": [
            "SI CUT OFF",
            "SI CUTOFF",
            "SI CUT-OFF",
            "SI CUT OFF DATE",
            "SI DEADLINE",
            "SI CLOSING",
            "SHIPPING INSTRUCTION CUT OFF",
            "SHIPPING INSTRUCTIONS CUT OFF",
            "SHIPPING INSTRUCTION CUTOFF",
            "SHIPPING INSTRUCTIONS CUTOFF",
            "SHIPPING INSTRUCTION DEADLINE",
            "SHIPPING INSTRUCTIONS DEADLINE",
            "SHIPPING INSTRUCTION CLOSING",
            "SHIPPING INSTRUCTIONS CLOSING",
            "S/I CUT OFF",
            "S/I CUTOFF",
            "S.I. CUT OFF",
            "S.I. DEADLINE",
        ],
        "documentation_cutoff": [
            "DOCUMENTATION CUT OFF",
            "DOCUMENTATION CUTOFF",
            "DOCUMENT CUT OFF",
            "DOCUMENT CUTOFF",
            "DOC CUT OFF",
            "DOC CUTOFF",
            "DOC DEADLINE",
            "DOCUMENTATION DEADLINE",
            "DOCUMENT DEADLINE",
            "DOCUMENTATION CLOSING",
            "DOC CLOSING",
            "B/L INSTRUCTION CUT OFF",
            "BL INSTRUCTION CUT OFF",
            "BILL OF LADING INSTRUCTION CUT OFF",
            "DRAFT BL CUT OFF",
            "DRAFT B/L CUT OFF",
        ],
        "etd": [
            "ETD",
            "ETD DATE",
            "ETD POL",
            "ETD AT POL",
            "ESTIMATED DEPARTURE",
            "ESTIMATED TIME OF DEPARTURE",
            "EST DEPARTURE",
            "VESSEL DEPARTURE",
            "DEPARTURE DATE",
            "SAILING DATE",
            "EXPECTED DEPARTURE",
        ],
        "pol_eta": [
            "POL ETA",
            "ETA POL",
            "ETA AT POL",
            "ETA POL TERMINAL",
            "VESSEL ARRIVAL AT POL",
            "VESSEL ARRIVAL POL",
            "ARRIVAL AT POL",
            "EXPECTED ARRIVAL AT POL",
        ],
        "eta": [
            "ETA POD",
            "ETA AT POD",
            "POD ETA",
            "DESTINATION ETA",
            "FINAL DESTINATION ETA",
            "ETA DESTINATION",
            "ESTIMATED ARRIVAL",
            "ESTIMATED TIME OF ARRIVAL",
            "EXPECTED ARRIVAL",
            "ARRIVAL DATE",
            "ETA",
            "ETA DATE",
        ],
    }

    # Additional deadline concepts that do not currently have their own
    # database column. They are deliberately preserved under Other Deadlines.
    OTHER_DEADLINE_HINTS = [
        "AMS",
        "ACI",
        "ENS",
        "ISF",
        "DRAFT",
        "DRAFT BL",
        "DRAFT B/L",
        "OBL",
        "ORIGINAL BL",
        "ORIGINAL B/L",
        "BL",
        "B/L",
        "CUSTOMS",
        "MANIFEST",
        "PORT",
        "REEFER",
        "DG",
        "DANGEROUS GOODS",
        "HAZ",
        "HAZARDOUS",
        "IMO",
        "LATE GATE",
        "NO SHOW",
        "EMPTY PICKUP",
        "EMPTY PICK UP",
        "EMPTY RETURN",
        "DOC",
        "DOCUMENT",
        "CY",
        "CARGO",
        "TERMINAL",
        "GATE",
        "VGM",
        "SI",
        "SHIPPING INSTRUCTION",
    ]

    DEADLINE_WORDS = [
        "CUT OFF",
        "CUTOFF",
        "CUT-OFF",
        "CLOSING",
        "DEADLINE",
        "DUE",
        "LATEST",
        "LAST RECEIVING",
        "LAST ACCEPTANCE",
        "SUBMISSION",
        "SUBMIT BY",
        "RECEIVING UNTIL",
    ]

    BOILERPLATE_PREFIXES = [
        "THIS BOOKING CONFIRMATION",
        "THE MERCHANT",
        "THE CARRIER",
        "PLEASE NOTE",
        "NOTE THAT",
        "TERMS AND CONDITIONS",
        "SPECIAL NOTES",
        "FOR MORE INFORMATION",
        "HTTP",
        "WWW",
    ]

    def analyze(self, text: str) -> dict:
        text = self.clean_text(text)
        lines = self._lines(text)

        result = {
            "confirmation_revision":
                self._extract_revision(
                    text,
                    lines,
                ),

            "confirmation_date":
                self._extract_confirmation_date(
                    text,
                    lines,
                ),
        }

        # --------------------------------------------------
        # General labeled business fields
        # --------------------------------------------------

        continuation_by_field = {
            "port_of_receipt": 2,
            "port_of_loading": 2,
            "pol_terminal": 2,
            "port_of_discharge": 2,
            "final_destination": 2,
            "empty_pick_up_at": 2,
            "inland_return_to": 2,
            "commodity": 2,
            "shipper": 1,
        }

        general_evidence = {}

        for (
            field_name,
            aliases,
        ) in self.FIELD_ALIASES.items():

            entries = self._extract_alias_entries(
                lines,
                aliases,
                continuation_lines=(
                    continuation_by_field.get(
                        field_name,
                        0,
                    )
                ),
            )

            entries = self._filter_entries_for_field(
                field_name,
                entries,
            )

            result[
                field_name
            ] = (
                entries[0]["value"]
                if entries
                else ""
            )

            if entries:

                general_evidence[
                    field_name
                ] = entries[0].get(
                    "line",
                    "",
                )

        # Booking No / Application No can share one line.
        self._extract_shared_identifiers(
            text,
            result,
        )

        # Capture exact source lines for important identifiers.
        for evidence_field, aliases in [
            (
                "carrier_booking_no",
                self.FIELD_ALIASES[
                    "carrier_booking_no"
                ],
            ),
            (
                "application_no",
                self.FIELD_ALIASES[
                    "application_no"
                ],
            ),
        ]:

            if result.get(
                evidence_field
            ):

                evidence_entries = self._extract_alias_entries(
                    lines,
                    aliases,
                    continuation_lines=0,
                )

                evidence_entries = self._filter_entries_for_field(
                    evidence_field,
                    evidence_entries,
                )

                if evidence_entries:

                    general_evidence[
                        evidence_field
                    ] = evidence_entries[0].get(
                        "line",
                        "",
                    )

        # If VESSEL/VOYAGE is printed as a label-only line, read the
        # following line before falling back to separate VESSEL and VOYAGE.
        if not result.get(
            "vessel_voyage"
        ):

            combined_entries = self._extract_alias_entries(
                lines,
                self.FIELD_ALIASES[
                    "vessel_voyage"
                ],
                continuation_lines=3,
            )

            combined_entries = [
                entry
                for entry in combined_entries
                if entry.get(
                    "score",
                    0,
                ) >= 0.99
            ]

            for combined_entry in combined_entries:

                combined_value = self._clean_business_value(
                    combined_entry.get(
                        "value",
                        "",
                    )
                )

                if not combined_value:
                    continue

                result[
                    "vessel_voyage"
                ] = combined_value

                general_evidence[
                    "vessel_voyage"
                ] = combined_entry.get(
                    "line",
                    "",
                )

                break

        # Some carriers use separate VESSEL and VOYAGE labels.
        if not result.get(
            "vessel_voyage"
        ):

            vessel_entries = self._extract_alias_entries(
                lines,
                self.VESSEL_ALIASES,
                continuation_lines=3,
            )

            voyage_entries = self._extract_alias_entries(
                lines,
                self.VOYAGE_ALIASES,
                continuation_lines=3,
            )

            vessel = ""
            vessel_source = ""

            for vessel_entry in vessel_entries:

                candidate_vessel = self._clean_business_value(
                    vessel_entry.get(
                        "value",
                        "",
                    )
                )

                if candidate_vessel:
                    vessel = candidate_vessel
                    vessel_source = vessel_entry.get(
                        "line",
                        "",
                    )
                    break

            voyage = ""
            voyage_source = ""

            for voyage_entry in voyage_entries:

                candidate_voyage = self._clean_business_value(
                    voyage_entry.get(
                        "value",
                        "",
                    )
                )

                if candidate_voyage:
                    voyage = candidate_voyage
                    voyage_source = voyage_entry.get(
                        "line",
                        "",
                    )
                    break

            if vessel and voyage:

                result[
                    "vessel_voyage"
                ] = (
                    f"{vessel} / {voyage}"
                )

                general_evidence[
                    "vessel_voyage"
                ] = (
                    f"{vessel_source} | {voyage_source}"
                ).strip(
                    " |"
                )

            elif vessel:

                result[
                    "vessel_voyage"
                ] = vessel

                general_evidence[
                    "vessel_voyage"
                ] = vessel_source

            elif voyage:

                result[
                    "vessel_voyage"
                ] = voyage

                general_evidence[
                    "vessel_voyage"
                ] = voyage_source

        # --------------------------------------------------
        # Deadlines / schedule
        # --------------------------------------------------

        deadline_entries = {}

        for (
            field_name,
            aliases,
        ) in self.DEADLINE_ALIASES.items():

            deadline_entries[
                field_name
            ] = self._extract_alias_entries(
                lines,
                aliases,
                continuation_lines=3,
                prefer_datetime=True,
            )

        result["cy_cutoff"] = self._first_value(
            deadline_entries[
                "cy_cutoff"
            ]
        )

        result["vgm_cutoff"] = self._first_value(
            deadline_entries[
                "vgm_cutoff"
            ]
        )

        result["si_cutoff"] = self._first_value(
            deadline_entries[
                "si_cutoff"
            ]
        )

        result[
            "documentation_cutoff"
        ] = self._first_value(
            deadline_entries[
                "documentation_cutoff"
            ]
        )

        result["etd"] = self._first_value(
            deadline_entries[
                "etd"
            ]
        )

        explicit_pol_eta = self._first_value(
            deadline_entries[
                "pol_eta"
            ]
        )

        explicit_eta_entries = deadline_entries[
            "eta"
        ]

        result["pol_eta"] = explicit_pol_eta
        result["eta"] = ""

        if explicit_eta_entries:

            # Some alias lists overlap. De-duplicate equivalent ETA values
            # while preserving line order.
            eta_entries = self._dedupe_entries(
                explicit_eta_entries
            )

            if result["pol_eta"]:

                # Prefer a destination ETA that is not the already-known
                # POL ETA.
                for entry in reversed(
                    eta_entries
                ):

                    if not self._same_value(
                        entry["value"],
                        result[
                            "pol_eta"
                        ],
                    ):

                        result[
                            "eta"
                        ] = entry[
                            "value"
                        ]
                        break

            elif len(
                eta_entries
            ) == 1:

                entry = eta_entries[
                    0
                ]

                if self._eta_is_pol_context(
                    lines,
                    entry["index"],
                ):

                    result[
                        "pol_eta"
                    ] = entry[
                        "value"
                    ]

                else:

                    result[
                        "eta"
                    ] = entry[
                        "value"
                    ]

            else:

                etd_index = (
                    deadline_entries[
                        "etd"
                    ][0]["index"]
                    if deadline_entries[
                        "etd"
                    ]
                    else None
                )

                before_etd = [
                    entry
                    for entry in eta_entries
                    if (
                        etd_index is not None
                        and entry[
                            "index"
                        ] < etd_index
                    )
                ]

                if before_etd:

                    result[
                        "pol_eta"
                    ] = before_etd[-1][
                        "value"
                    ]

                result[
                    "eta"
                ] = eta_entries[-1][
                    "value"
                ]

                if (
                    not result[
                        "pol_eta"
                    ]
                    and len(
                        eta_entries
                    ) > 1
                ):

                    result[
                        "pol_eta"
                    ] = eta_entries[0][
                        "value"
                    ]

        # Semantic fallback for values not caught by exact aliases.
        self._semantic_deadline_fallback(
            lines,
            result,
        )

        result[
            "qty_type"
        ] = self._extract_qty_type(
            lines
        )

        result[
            "other_deadlines"
        ] = self._extract_other_deadlines(
            lines,
            result,
        )

        # Preserve source lines for human review.
        result[
            "__evidence__"
        ] = general_evidence

        # Final carrier-agnostic document-understanding pass.
        # This does not depend on a carrier template or page coordinates.
        result = self._document_understanding_pass(
            lines,
            result,
        )

        return result


    # ======================================================
    # Carrier-agnostic document-understanding pass
    # ======================================================

    IMPORTANT_REVIEW_FIELDS = [
        "carrier_booking_no",
        "vessel_voyage",
        "port_of_loading",
        "port_of_discharge",
        "cy_cutoff",
        "vgm_cutoff",
        "si_cutoff",
        "etd",
        "eta",
    ]

    DEADLINE_SEMANTIC_TERMS = {
        "cy_cutoff": {
            "strong": [
                "CY",
                "GATE IN",
                "GATE-IN",
                "CARGO CLOSING",
                "CARGO CUT OFF",
                "CARGO CUTOFF",
                "TERMINAL CLOSING",
                "TERMINAL CUT OFF",
                "TERMINAL CUTOFF",
                "FULL CONTAINER",
                "LADEN",
                "LAST RECEIVING",
                "LATEST GATE IN",
                "LATEST GATE-IN",
                "PORT CLOSING",
            ],
            "support": [
                "CARGO",
                "CONTAINER",
                "TERMINAL",
                "GATE",
                "PORT",
                "RECEIVING",
                "DELIVERY",
            ],
        },
        "vgm_cutoff": {
            "strong": [
                "VGM",
                "VERIFIED GROSS MASS",
            ],
            "support": [
                "WEIGHT",
                "SOLAS",
                "MASS",
            ],
        },
        "si_cutoff": {
            "strong": [
                "SI",
                "S/I",
                "SHIPPING INSTRUCTION",
                "SHIPPING INSTRUCTIONS",
            ],
            "support": [
                "INSTRUCTION",
                "SHIPPING DOC",
            ],
        },
        "documentation_cutoff": {
            "strong": [
                "DOCUMENTATION",
                "DOCUMENT CUT",
                "DOC CUT",
                "DOC DEADLINE",
                "DOCUMENT DEADLINE",
                "BL INSTRUCTION",
                "B/L INSTRUCTION",
                "BILL OF LADING INSTRUCTION",
                "DRAFT BL",
                "DRAFT B/L",
            ],
            "support": [
                "DOCUMENT",
                "DOC",
                "BILL OF LADING",
                "B/L",
                "BL",
                "DRAFT",
            ],
        },
        "etd": {
            "strong": [
                "ETD",
                "ESTIMATED TIME OF DEPARTURE",
                "ESTIMATED DEPARTURE",
                "EXPECTED DEPARTURE",
                "SAILING DATE",
                "VESSEL DEPARTURE",
            ],
            "support": [
                "DEPARTURE",
                "SAILING",
                "DEPART",
            ],
        },
        "pol_eta": {
            "strong": [
                "POL ETA",
                "ETA POL",
                "ETA AT POL",
                "ARRIVAL AT POL",
                "ARRIVAL POL",
                "VESSEL ARRIVAL AT POL",
                "ORIGIN ETA",
                "ETA ORIGIN",
            ],
            "support": [
                "POL",
                "PORT OF LOADING",
                "LOAD PORT",
                "LOADING PORT",
                "ORIGIN",
            ],
        },
        "eta": {
            "strong": [
                "ETA",
                "ESTIMATED TIME OF ARRIVAL",
                "ESTIMATED ARRIVAL",
                "EXPECTED ARRIVAL",
                "DESTINATION ETA",
                "POD ETA",
                "ETA POD",
                "VESSEL ARRIVAL",
            ],
            "support": [
                "ARRIVAL",
                "ARRIVE",
                "POD",
                "PORT OF DISCHARGE",
                "DISCHARGE PORT",
                "DESTINATION",
            ],
        },
    }

    GENERIC_DEADLINE_TERMS = [
        "CUT OFF",
        "CUTOFF",
        "CUT-OFF",
        "CLOSING",
        "DEADLINE",
        "DUE",
        "LATEST",
        "LAST RECEIVING",
        "LAST ACCEPTANCE",
        "SUBMIT BY",
        "SUBMISSION",
        "RECEIVING UNTIL",
    ]

    @classmethod
    def _document_understanding_pass(
        cls,
        lines,
        result,
    ):
        """
        Final semantic pass over the document.

        The earlier parser handles exact/known aliases efficiently. This
        pass is deliberately template-independent: it scans every date/time
        candidate, looks at its surrounding words, and classifies the
        meaning of the candidate. This makes layout changes much less
        important than the language surrounding a value.

        Hidden metadata keys begin with "__" so the app can display review
        information without saving them into Excel/database business fields.
        """

        output = dict(result)

        confidence = {
            key: (
                0.88
                if cls._clean_business_value(
                    value
                )
                else 0.0
            )
            for key, value in output.items()
            if not str(key).startswith(
                "__"
            )
        }

        evidence = dict(
            output.get(
                "__evidence__",
                {},
            )
            or {}
        )

        # Repair a common false positive where a document title such as
        # "CARRIER BOOKING ADVICE" is mistaken for the Carrier field.
        current_carrier = cls._clean_business_value(
            output.get(
                "carrier",
                "",
            )
        )

        normalized_current_carrier = cls._normalize_label(
            current_carrier
        )

        carrier_looks_like_title = any(
            term in normalized_current_carrier
            for term in [
                "BOOKING ADVICE",
                "BOOKING CONFIRMATION",
                "RESERVATION CONFIRMATION",
                "BOOKING NOTE",
            ]
        )

        if (
            not current_carrier
            or carrier_looks_like_title
        ):

            carrier_entries = cls._extract_alias_entries(
                lines,
                cls.FIELD_ALIASES[
                    "carrier"
                ],
                continuation_lines=1,
            )

            carrier_entries = cls._filter_entries_for_field(
                "carrier",
                carrier_entries,
            )

            for carrier_entry in carrier_entries:

                normalized_source_line = cls._normalize_label(
                    carrier_entry.get(
                        "line",
                        "",
                    )
                )

                if any(
                    title_term in normalized_source_line
                    for title_term in [
                        "CARRIER BOOKING ADVICE",
                        "CARRIER BOOKING CONFIRMATION",
                        "BOOKING CONFIRMATION",
                        "RESERVATION CONFIRMATION",
                    ]
                ):

                    continue

                candidate_carrier = cls._clean_business_value(
                    carrier_entry.get(
                        "value",
                        "",
                    )
                )

                if not candidate_carrier:
                    continue

                output[
                    "carrier"
                ] = candidate_carrier

                confidence[
                    "carrier"
                ] = 0.92
                break

        candidates = cls._collect_semantic_deadline_candidates(
            lines
        )

        # Sort strongest first. A high semantic score may fill a field even
        # when the carrier changes the layout/wording.
        candidates = sorted(
            candidates,
            key=lambda item: (
                item["score"],
                -item["index"],
            ),
            reverse=True,
        )

        for candidate in candidates:

            field_name = candidate[
                "field"
            ]

            value = candidate[
                "value"
            ]

            current = cls._clean_business_value(
                output.get(
                    field_name,
                    "",
                )
            )

            candidate_confidence = min(
                0.99,
                0.62
                + (
                    candidate[
                        "score"
                    ]
                    * 0.045
                ),
            )

            should_replace = False

            if not current:
                should_replace = True

            elif not cls._looks_like_datetime(
                current
            ):
                should_replace = True

            # ETA/POL ETA are special because many documents print two ETAs.
            if (
                field_name == "pol_eta"
                and current
            ):
                should_replace = False

            if (
                field_name == "eta"
                and current
                and cls._eta_is_pol_context(
                    lines,
                    candidate[
                        "index"
                    ],
                )
            ):
                should_replace = False

            if should_replace:

                output[
                    field_name
                ] = value

                confidence[
                    field_name
                ] = candidate_confidence

                evidence[
                    field_name
                ] = candidate[
                    "context"
                ]

        # Reconcile carriers that print Vessel and Voyage as two separate
        # labels. This also fixes cases where a fuzzy Vessel/Voyage match
        # initially captured only the vessel name.
        vessel_entries = cls._extract_strict_separate_entries(
            lines,
            cls.VESSEL_ALIASES,
            forbidden_terms=[
                "VOYAGE",
                "VOY",
            ],
        )

        voyage_entries = cls._extract_strict_separate_entries(
            lines,
            cls.VOYAGE_ALIASES,
            forbidden_terms=[
                "VESSEL",
                "VSL",
            ],
        )

        vessel_value = (
            cls._clean_business_value(
                vessel_entries[0][
                    "value"
                ]
            )
            if vessel_entries
            else ""
        )

        voyage_value = (
            cls._clean_business_value(
                voyage_entries[0][
                    "value"
                ]
            )
            if voyage_entries
            else ""
        )

        current_vessel_voyage = cls._clean_business_value(
            output.get(
                "vessel_voyage",
                "",
            )
        )

        explicit_combined_label = False

        for combined_line in lines:

            combined_label, combined_value = (
                cls._split_obvious_label_value(
                    combined_line
                )
            )

            normalized_combined_label = (
                cls._normalize_label(
                    combined_label
                )
            )

            has_vessel_word = (
                cls._semantic_term_present(
                    normalized_combined_label,
                    "VESSEL",
                )
                or cls._semantic_term_present(
                    normalized_combined_label,
                    "VSL",
                )
            )

            has_voyage_word = (
                cls._semantic_term_present(
                    normalized_combined_label,
                    "VOYAGE",
                )
                or cls._semantic_term_present(
                    normalized_combined_label,
                    "VOY",
                )
            )

            if (
                has_vessel_word
                and has_voyage_word
                and cls._clean_business_value(
                    combined_value
                )
            ):

                explicit_combined_label = True
                break

        if (
            vessel_value
            and voyage_value
            and not explicit_combined_label
        ):

            normalized_current = cls._normalize_label(
                current_vessel_voyage
            )

            normalized_vessel = cls._normalize_label(
                vessel_value
            )

            normalized_voyage = cls._normalize_label(
                voyage_value
            )

            if (
                not current_vessel_voyage
                or normalized_vessel
                not in normalized_current
                or normalized_voyage
                not in normalized_current
            ):

                output[
                    "vessel_voyage"
                ] = (
                    f"{vessel_value} / {voyage_value}"
                )

                confidence[
                    "vessel_voyage"
                ] = max(
                    confidence.get(
                        "vessel_voyage",
                        0.0,
                    ),
                    0.94,
                )

        # If there are multiple ETA-like candidates, classify origin vs
        # destination from local context instead of relying on order alone.
        cls._resolve_semantic_eta_candidates(
            lines,
            output,
            confidence,
            evidence,
            candidates,
        )

        unknown_deadlines = (
            cls._collect_unknown_semantic_deadlines(
                lines,
                candidates,
            )
        )

        existing_other = cls._clean_business_value(
            output.get(
                "other_deadlines",
                "",
            )
        )

        combined_other = []

        if existing_other:
            combined_other.extend(
                line.strip()
                for line in existing_other.splitlines()
                if line.strip()
            )

        combined_other.extend(
            unknown_deadlines
        )

        unique_other = []
        seen_other = set()

        for item in combined_other:

            normalized = cls._normalize_label(
                item
            )

            if (
                not normalized
                or normalized in seen_other
            ):
                continue

            seen_other.add(
                normalized
            )
            unique_other.append(
                item
            )

        output[
            "other_deadlines"
        ] = "\n".join(
            unique_other
        )

        if unique_other:
            confidence[
                "other_deadlines"
            ] = max(
                confidence.get(
                    "other_deadlines",
                    0.0,
                ),
                0.78,
            )

        review_notes = []

        text_joined = " ".join(
            lines
        )

        text_chars = len(
            re.sub(
                r"\s+",
                "",
                text_joined,
            )
        )

        if text_chars < 80:

            review_notes.append(
                "Very little usable text was extracted. The file may be "
                "a scanned/image PDF or may have an unusual text layer."
            )

        for field_name in (
            cls.IMPORTANT_REVIEW_FIELDS
        ):

            value = cls._clean_business_value(
                output.get(
                    field_name,
                    "",
                )
            )

            if not value:

                review_notes.append(
                    "Not detected: "
                    + field_name
                )

            elif confidence.get(
                field_name,
                0.0,
            ) < 0.75:

                review_notes.append(
                    "Review low-confidence field: "
                    + field_name
                )

        output[
            "__confidence__"
        ] = confidence

        output[
            "__evidence__"
        ] = evidence

        output[
            "__review_notes__"
        ] = review_notes

        output[
            "__text_quality__"
        ] = (
            "LOW"
            if text_chars < 80
            else "OK"
        )

        return output

    @classmethod
    def _extract_strict_separate_entries(
        cls,
        lines,
        aliases,
        forbidden_terms,
    ):
        """
        Extract a standalone label such as "Vessel Name" or "Voyage No".
        Combined labels such as "VESSEL/VOYAGE" are intentionally ignored.
        """

        output = []

        for index, line in enumerate(
            lines
        ):

            label, obvious_value = (
                cls._split_obvious_label_value(
                    line
                )
            )

            normalized_label = (
                cls._normalize_label(
                    label
                )
            )

            if any(
                cls._semantic_term_present(
                    normalized_label,
                    cls._normalize_label(
                        term
                    ),
                )
                for term in forbidden_terms
            ):

                continue

            score = cls._best_alias_score(
                label,
                aliases,
            )

            if score < 0.92:
                continue

            value = cls._clean_business_value(
                obvious_value
            )

            if not value:

                remainder = cls._remove_alias_prefix(
                    line,
                    aliases,
                )

                value = cls._clean_business_value(
                    remainder
                )

            if not value:

                for next_index in range(
                    index + 1,
                    min(
                        len(
                            lines
                        ),
                        index + 5,
                    ),
                ):

                    raw_candidate = lines[
                        next_index
                    ].strip()

                    candidate = cls._clean_business_value(
                        raw_candidate
                    )

                    if not candidate:
                        continue

                    if cls._is_known_label_line(
                        raw_candidate
                    ):
                        break

                    value = candidate
                    break

            if not value:
                continue

            if cls._is_boilerplate(
                value
            ):
                continue

            output.append(
                {
                    "index": index,
                    "value": value,
                    "score": score,
                    "line": line,
                }
            )

        return output


    @classmethod
    def _collect_semantic_deadline_candidates(
        cls,
        lines,
    ):
        candidates = []

        for index, line in enumerate(
            lines
        ):

            window_start = max(
                0,
                index - 2,
            )

            window_end = min(
                len(lines),
                index + 4,
            )

            local_lines = lines[
                window_start:
                window_end
            ]

            context = " ".join(
                local_lines
            )

            # A deadline/schedule value can be on the same line or one of
            # the next few lines.
            value = cls._line_deadline_value(
                lines,
                index,
            )

            if not value:

                if cls._looks_like_datetime(
                    line
                ):
                    value = line.strip()
                else:
                    continue

            if not cls._looks_like_datetime(
                value
            ):
                continue

            label_context = cls._semantic_label_context(
                lines,
                index,
                value,
            )

            scores = cls._score_deadline_semantics(
                label_context
            )

            if not scores:
                continue

            best_field, best_score = max(
                scores.items(),
                key=lambda item: item[1],
            )

            if best_score < 4.0:
                continue

            candidates.append(
                {
                    "index":
                        index,

                    "field":
                        best_field,

                    "score":
                        best_score,

                    "value":
                        cls._clean_candidate_datetime_value(
                            value
                        ),

                    "context":
                        context,
                }
            )

        # Unique by field/value/index vicinity.
        output = []
        seen = set()

        for candidate in candidates:

            key = (
                candidate["field"],
                cls._normalize_label(
                    candidate["value"]
                ),
            )

            if key in seen:
                continue

            seen.add(
                key
            )
            output.append(
                candidate
            )

        return output

    @classmethod
    def _semantic_label_context(
        cls,
        lines,
        index,
        value,
    ):
        pieces = []

        # Prefer the current line and preceding labels; avoid pulling too
        # much text from the following business/legal paragraphs.
        for pos in range(
            max(0, index - 2),
            min(len(lines), index + 2),
        ):

            candidate = lines[
                pos
            ].strip()

            if not candidate:
                continue

            pieces.append(
                candidate
            )

        context = " ".join(
            pieces
        )

        # Remove the date/time value so numeric content does not influence
        # semantic classification.
        if value:
            context = context.replace(
                value,
                " ",
            )

        return cls._normalize_label(
            context
        )

    @classmethod
    def _score_deadline_semantics(
        cls,
        context,
    ):
        normalized = cls._normalize_label(
            context
        )

        if not normalized:
            return {}

        scores = {
            field_name: 0.0
            for field_name
            in cls.DEADLINE_SEMANTIC_TERMS
        }

        has_generic_deadline = any(
            cls._normalize_label(
                term
            ) in normalized
            for term in cls.GENERIC_DEADLINE_TERMS
        )

        for field_name, terms in (
            cls.DEADLINE_SEMANTIC_TERMS.items()
        ):

            for term in terms[
                "strong"
            ]:

                normalized_term = (
                    cls._normalize_label(
                        term
                    )
                )

                if cls._semantic_term_present(
                    normalized,
                    normalized_term,
                ):

                    scores[
                        field_name
                    ] += 5.0

            for term in terms[
                "support"
            ]:

                normalized_term = (
                    cls._normalize_label(
                        term
                    )
                )

                if cls._semantic_term_present(
                    normalized,
                    normalized_term,
                ):

                    scores[
                        field_name
                    ] += 1.5

        # Cut-off fields become stronger when a generic deadline word exists.
        if has_generic_deadline:

            for field_name in [
                "cy_cutoff",
                "vgm_cutoff",
                "si_cutoff",
                "documentation_cutoff",
            ]:

                if scores[
                    field_name
                ] > 0:

                    scores[
                        field_name
                    ] += 2.0

        # Explicit shipping acronyms must stay distinct.
        if cls._semantic_term_present(
            normalized,
            "ETD",
        ):

            scores[
                "etd"
            ] += 7.0

            scores[
                "eta"
            ] = max(
                0.0,
                scores[
                    "eta"
                ] - 6.0,
            )

            scores[
                "pol_eta"
            ] = max(
                0.0,
                scores[
                    "pol_eta"
                ] - 6.0,
            )

        if cls._semantic_term_present(
            normalized,
            "ETA",
        ):

            scores[
                "eta"
            ] += 4.0

            scores[
                "etd"
            ] = max(
                0.0,
                scores[
                    "etd"
                ] - 6.0,
            )

        if (
            cls._semantic_term_present(
                normalized,
                "ETA",
            )
            and any(
                cls._semantic_term_present(
                    normalized,
                    cls._normalize_label(
                        term
                    ),
                )
                for term in [
                    "POL",
                    "PORT OF LOADING",
                    "LOADING PORT",
                    "LOAD PORT",
                    "ORIGIN",
                ]
            )
        ):

            scores[
                "pol_eta"
            ] += 8.0

            scores[
                "eta"
            ] = max(
                0.0,
                scores[
                    "eta"
                ] - 2.0,
            )

        if (
            cls._semantic_term_present(
                normalized,
                "ETA",
            )
            and any(
                cls._semantic_term_present(
                    normalized,
                    cls._normalize_label(
                        term
                    ),
                )
                for term in [
                    "POD",
                    "PORT OF DISCHARGE",
                    "DISCHARGE PORT",
                    "DESTINATION",
                    "FINAL DESTINATION",
                ]
            )
        ):

            scores[
                "eta"
            ] += 7.0

            scores[
                "pol_eta"
            ] = max(
                0.0,
                scores[
                    "pol_eta"
                ] - 3.0,
            )

        # Keep only meaningful scores.
        return {
            key: value
            for key, value in scores.items()
            if value > 0
        }

    @staticmethod
    def _semantic_term_present(
        normalized_context,
        normalized_term,
    ):
        if not normalized_term:
            return False

        # Acronyms need token boundaries so SI is not found inside another
        # word. Multiword phrases can use ordinary containment.
        if (
            " " not in normalized_term
            and len(normalized_term) <= 4
        ):

            return bool(
                re.search(
                    r"\b"
                    + re.escape(
                        normalized_term
                    )
                    + r"\b",
                    normalized_context,
                )
            )

        return (
            normalized_term
            in normalized_context
        )

    @classmethod
    def _resolve_semantic_eta_candidates(
        cls,
        lines,
        output,
        confidence,
        evidence,
        candidates,
    ):
        eta_candidates = [
            candidate
            for candidate in candidates
            if candidate[
                "field"
            ] in {
                "eta",
                "pol_eta",
            }
        ]

        if not eta_candidates:
            return

        explicit_pol = [
            candidate
            for candidate in eta_candidates
            if candidate[
                "field"
            ] == "pol_eta"
        ]

        destination = [
            candidate
            for candidate in eta_candidates
            if candidate[
                "field"
            ] == "eta"
            and not cls._eta_is_pol_context(
                lines,
                candidate[
                    "index"
                ],
            )
        ]

        if explicit_pol:

            best = max(
                explicit_pol,
                key=lambda item: item[
                    "score"
                ],
            )

            current = cls._clean_business_value(
                output.get(
                    "pol_eta",
                    "",
                )
            )

            if (
                not current
                or not cls._looks_like_datetime(
                    current
                )
            ):

                output[
                    "pol_eta"
                ] = best[
                    "value"
                ]

                confidence[
                    "pol_eta"
                ] = min(
                    0.99,
                    0.65
                    + best[
                        "score"
                    ]
                    * 0.04,
                )

                evidence[
                    "pol_eta"
                ] = best[
                    "context"
                ]

        if destination:

            # In multi-leg documents, the last destination-like ETA is
            # generally the final destination ETA. The user still reviews it
            # before save.
            best = max(
                destination,
                key=lambda item: (
                    item[
                        "score"
                    ],
                    item[
                        "index"
                    ],
                ),
            )

            current = cls._clean_business_value(
                output.get(
                    "eta",
                    "",
                )
            )

            if (
                not current
                or not cls._looks_like_datetime(
                    current
                )
            ):

                output[
                    "eta"
                ] = best[
                    "value"
                ]

                confidence[
                    "eta"
                ] = min(
                    0.99,
                    0.65
                    + best[
                        "score"
                    ]
                    * 0.04,
                )

                evidence[
                    "eta"
                ] = best[
                    "context"
                ]

    @classmethod
    def _collect_unknown_semantic_deadlines(
        cls,
        lines,
        known_candidates,
    ):
        known_keys = {
            (
                candidate[
                    "index"
                ],
                cls._normalize_label(
                    candidate[
                        "value"
                    ]
                ),
            )
            for candidate
            in known_candidates
        }

        output = []

        for index, line in enumerate(
            lines
        ):

            normalized = cls._normalize_label(
                line
            )

            has_deadline_word = any(
                cls._semantic_term_present(
                    normalized,
                    cls._normalize_label(
                        term
                    ),
                )
                for term in (
                    cls.GENERIC_DEADLINE_TERMS
                )
            )

            if not has_deadline_word:
                continue

            value = cls._line_deadline_value(
                lines,
                index,
            )

            if (
                not value
                or not cls._looks_like_datetime(
                    value
                )
            ):
                continue

            key = (
                index,
                cls._normalize_label(
                    value
                ),
            )

            if key in known_keys:
                continue

            scores = cls._score_deadline_semantics(
                cls._semantic_label_context(
                    lines,
                    index,
                    value,
                )
            )

            if (
                scores
                and max(
                    scores.values()
                ) >= 4.0
            ):
                continue

            label, _ = (
                cls._split_obvious_label_value(
                    line
                )
            )

            label = label.strip(
                " :-–—"
            )

            if not label:
                label = line.strip(
                    " :-–—"
                )

            output.append(
                f"{label}: "
                f"{cls._clean_candidate_datetime_value(value)}"
            )

        return output

    @staticmethod
    def _clean_business_value(
        value,
    ):
        if value is None:
            return ""

        if isinstance(
            value,
            (
                dict,
                list,
                tuple,
                set,
            ),
        ):
            return ""

        cleaned = str(
            value
        ).strip()

        if not cleaned:
            return ""

        # Visual/table filler from PDF extraction is not business data.
        if re.fullmatch(
            r"[\s.\-_/\\:;|,*]+",
            cleaned,
        ):
            return ""

        return cleaned

    @classmethod
    def _clean_candidate_datetime_value(
        cls,
        value,
    ):
        value = str(
            value
            or ""
        ).strip()

        # Avoid accidentally carrying a following field label into a
        # date/time value.
        pieces = [
            piece.strip()
            for piece in value.splitlines()
            if piece.strip()
        ]

        if len(
            pieces
        ) <= 1:
            return value

        kept = []

        for piece in pieces:

            if (
                kept
                and cls._is_known_label_line(
                    piece
                )
            ):
                break

            kept.append(
                piece
            )

        return "\n".join(
            kept
        ).strip()

    # ======================================================
    # Text normalization
    # ======================================================

    @staticmethod
    def clean_text(
        text: str,
    ) -> str:

        if not text:
            return ""

        text = str(
            text
        ).replace(
            "\r\n",
            "\n",
        ).replace(
            "\r",
            "\n",
        )

        text = text.replace(
            "\u00a0",
            " ",
        ).replace(
            "\ufeff",
            "",
        )

        # Preserve newlines but normalize horizontal spacing.
        text = re.sub(
            r"[ \t]+",
            " ",
            text,
        )

        text = re.sub(
            r"\n{3,}",
            "\n\n",
            text,
        )

        return text.strip()

    @staticmethod
    def _lines(
        text: str,
    ):

        return [
            line.strip()
            for line in text.splitlines()
            if line.strip()
        ]

    @staticmethod
    def _strip_accents(
        value: str,
    ) -> str:

        normalized = unicodedata.normalize(
            "NFKD",
            str(
                value
                or ""
            ),
        )

        return "".join(
            char
            for char in normalized
            if not unicodedata.combining(
                char
            )
        )

    @classmethod
    def _normalize_label(
        cls,
        value: str,
    ) -> str:

        value = cls._strip_accents(
            value
        ).upper()

        value = value.replace(
            "&",
            " AND ",
        )

        value = re.sub(
            r"[\[\](){}]",
            " ",
            value,
        )

        value = re.sub(
            r"[/_.\-]+",
            " ",
            value,
        )

        value = re.sub(
            r"[^A-Z0-9# ]+",
            " ",
            value,
        )

        value = re.sub(
            r"\s+",
            " ",
            value,
        ).strip()

        # Canonical synonym cleanup for matching only.
        replacements = {
            "CUT OFF":
                "CUTOFF",

            "CUTOFF DATE TIME":
                "CUTOFF DATE TIME",

            "NUMBER":
                "NO",

            "REFERENCE":
                "REF",

            "SHIPPING INSTRUCTIONS":
                "SHIPPING INSTRUCTION",

            "DOCUMENTS":
                "DOCUMENT",

            "DOCUMENTATION":
                "DOCUMENTATION",
        }

        for source, target in (
            replacements.items()
        ):

            value = re.sub(
                r"\b"
                + re.escape(
                    source
                )
                + r"\b",
                target,
                value,
            )

        return re.sub(
            r"\s+",
            " ",
            value,
        ).strip()

    @classmethod
    def _alias_score(
        cls,
        label: str,
        alias: str,
    ) -> float:

        left = cls._normalize_label(
            label
        )

        right = cls._normalize_label(
            alias
        )

        if not left or not right:
            return 0.0

        if left == right:
            return 1.0

        left_tokens_list = left.split()
        right_tokens_list = right.split()

        left_tokens = set(
            left_tokens_list
        )

        right_tokens = set(
            right_tokens_list
        )

        # Shipping acronyms are semantically distinct even when only one
        # letter differs (ETA vs ETD, POL vs POD). Check this BEFORE fuzzy
        # prefix logic so "FINAL DESTINATION" cannot match "DESTINATION ETA".
        protected_tokens = {
            "ETA",
            "ETD",
            "POL",
            "POD",
            "POR",
            "VGM",
            "SI",
            "CY",
            "FCL",
        }

        for token in protected_tokens:

            if (
                token in right_tokens
                and token not in left_tokens
            ):

                return 0.0

        # Strong prefix match for labels such as
        # "VGM CUTOFF VIA EDI WEB APP".
        if left.startswith(
            right + " "
        ):

            return 0.97

        # Allow a shorter left label only when it is nearly the complete
        # alias. This supports small suffixes such as "DATE" but prevents
        # generic words like "DESTINATION" matching "DESTINATION ETA".
        if right.startswith(
            left + " "
        ):

            if (
                len(
                    left_tokens_list
                )
                >= max(
                    2,
                    len(
                        right_tokens_list
                    ) - 1,
                )
            ):

                return 0.94

        # Token-subset matches are allowed only for short label-like text,
        # never for long explanatory prose.
        if (
            right_tokens
            and right_tokens.issubset(
                left_tokens
            )
            and len(
                left_tokens_list
            )
            <= len(
                right_tokens_list
            ) + 4
            and (
                not right_tokens_list
                or left_tokens_list[
                    0
                ] == right_tokens_list[
                    0
                ]
            )
        ):

            return 0.93

        # Fuzzy matching is useful for minor spelling/punctuation noise, but
        # only on short label-like strings.
        if (
            len(
                left_tokens_list
            )
            > len(
                right_tokens_list
            ) + 4
        ):

            return 0.0

        return SequenceMatcher(
            None,
            left,
            right,
        ).ratio()

    @classmethod
    def _best_alias_score(
        cls,
        label: str,
        aliases,
    ) -> float:

        return max(
            (
                cls._alias_score(
                    label,
                    alias,
                )
                for alias
                in aliases
            ),
            default=0.0,
        )

    @classmethod
    def _filter_entries_for_field(
        cls,
        field_name,
        entries,
    ):
        """
        Remove source lines that only matched because a generic alias was
        contained inside a different business label.

        Example:
            CARRIER BOOKING NO: ABC123
        must feed Carrier Booking No, never Carrier.
        """

        forbidden_terms = cls.FIELD_LABEL_FORBIDDEN_TERMS.get(
            field_name,
            [],
        )

        if not forbidden_terms:
            return entries

        filtered = []

        for entry in entries:

            source_line = cls._normalize_label(
                entry.get(
                    "line",
                    "",
                )
            )

            obvious_label, _ = cls._split_obvious_label_value(
                entry.get(
                    "line",
                    "",
                )
            )

            normalized_label = cls._normalize_label(
                obvious_label
            )

            rejected = False

            for forbidden in forbidden_terms:

                forbidden_normalized = cls._normalize_label(
                    forbidden
                )

                if not forbidden_normalized:
                    continue

                if re.search(
                    r"\b"
                    + re.escape(
                        forbidden_normalized
                    )
                    + r"\b",
                    normalized_label,
                ):
                    rejected = True
                    break

            # Additional value-side safety for Carrier.
            if (
                field_name == "carrier"
                and not rejected
            ):

                candidate_value = cls._normalize_label(
                    entry.get(
                        "value",
                        "",
                    )
                )

                if any(
                    bad in candidate_value
                    for bad in [
                        "BOOKING NO",
                        "BOOKING NUMBER",
                        "BOOKING REF",
                        "BOOKING REFERENCE",
                        "RESERVATION NO",
                        "RESERVATION NUMBER",
                    ]
                ):
                    rejected = True

            if not rejected:
                filtered.append(
                    entry
                )

        return filtered


    # ======================================================
    # Generic label/value extraction
    # ======================================================

    @staticmethod
    def _split_obvious_label_value(
        line: str,
    ):

        # Colon is the most reliable separator.
        if ":" in line:

            left, right = line.split(
                ":",
                1,
            )

            return (
                left.strip(),
                right.strip(),
            )

        # Tab is common in spreadsheet-generated PDFs.
        if "\t" in line:

            pieces = [
                piece.strip()
                for piece in line.split(
                    "\t"
                )
                if piece.strip()
            ]

            if len(
                pieces
            ) >= 2:

                return (
                    pieces[0],
                    " ".join(
                        pieces[1:]
                    ),
                )

        return (
            line.strip(),
            "",
        )

    @classmethod
    def _remove_alias_prefix(
        cls,
        line: str,
        aliases,
    ) -> str:

        raw = line.strip()

        # First try direct raw-text aliases with flexible punctuation.
        for alias in sorted(
            aliases,
            key=len,
            reverse=True,
        ):

            tokens = re.findall(
                r"[A-Za-z0-9#]+",
                cls._strip_accents(
                    alias
                ),
            )

            if not tokens:
                continue

            pattern = (
                r"^\s*"
                + r"[\s/_.\-]*".join(
                    re.escape(
                        token
                    )
                    for token in tokens
                )
                + r"\b"
            )

            match = re.match(
                pattern,
                cls._strip_accents(
                    raw
                ),
                re.IGNORECASE,
            )

            if match:

                # Use the same character offsets because accent stripping
                # keeps character count for ordinary carrier labels.
                remainder = raw[
                    match.end():
                ].strip()

                remainder = re.sub(
                    r"^[\s:;=\-–—]+",
                    "",
                    remainder,
                ).strip()

                # Aliases are checked longest-first. Once the longest alias
                # matches, do not fall through to a shorter alias and turn
                # suffix words such as "NAME" or "NO" into a fake value.
                return remainder

        # Fallback: obvious colon split.
        left, right = (
            cls._split_obvious_label_value(
                raw
            )
        )

        if (
            right
            and cls._best_alias_score(
                left,
                aliases,
            )
            >= 0.84
        ):

            return right

        return ""

    @classmethod
    def _is_known_label_line(
        cls,
        line: str,
    ) -> bool:

        label, _ = (
            cls._split_obvious_label_value(
                line
            )
        )

        all_groups = list(
            cls.FIELD_ALIASES.values()
        ) + list(
            cls.DEADLINE_ALIASES.values()
        ) + [
            cls.VESSEL_ALIASES,
            cls.VOYAGE_ALIASES,
        ]

        for aliases in all_groups:

            if (
                cls._best_alias_score(
                    label,
                    aliases,
                )
                >= 0.90
            ):

                return True

        normalized = cls._normalize_label(
            line
        )

        stop_prefixes = [
            "REMARK",
            "REMARKS",
            "PROPER SHIPPING NAME",
            "QTY TYPE",
            "SPECIAL NOTES",
            "TERMS AND CONDITIONS",
            "PAYMENT TERM",
            "SERVICE CONTRACT",
            "SHIPPER",
            "CONSIGNEE",
            "NOTIFY",
            "BOOKING CONFIRMATION",
        ]

        if any(
            normalized.startswith(
                cls._normalize_label(
                    prefix
                )
            )
            for prefix
            in stop_prefixes
        ):

            return True

        # Generic semantic labels should also terminate the previous field,
        # even if a carrier uses wording we have never seen before.
        semantic_deadline_words = [
            "CUTOFF",
            "CUT OFF",
            "CLOSING",
            "DEADLINE",
            "LATEST",
            "LAST RECEIVING",
            "SUBMIT BY",
            "SUBMISSION",
            "ETA",
            "ETD",
            "DEPARTURE",
            "ARRIVAL",
            "SAILING",
        ]

        if any(
            cls._semantic_term_present(
                normalized,
                cls._normalize_label(
                    term
                ),
            )
            for term in semantic_deadline_words
        ):

            return True

        return False

    @classmethod
    def _is_boilerplate(
        cls,
        line: str,
    ) -> bool:

        normalized = cls._normalize_label(
            line
        )

        if len(
            line
        ) > 180:
            return True

        return any(
            normalized.startswith(
                cls._normalize_label(
                    prefix
                )
            )
            for prefix
            in cls.BOILERPLATE_PREFIXES
        )

    @classmethod
    def _looks_like_datetime(
        cls,
        value: str,
    ) -> bool:

        value = str(
            value
            or ""
        )

        patterns = [
            # 2026/04/30, 2026-04-30, 2026.04.30
            r"\b20\d{2}[/.\-]\d{1,2}[/.\-]\d{1,2}\b",

            # 30/04/2026, 30-04-2026
            r"\b\d{1,2}[/.\-]\d{1,2}[/.\-](?:20)?\d{2}\b",

            # 30 APR 2026 / 30-APR-2026
            r"\b\d{1,2}[\s\-/.]+"
            r"(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|SEPT|OCT|NOV|DEC)"
            r"[A-Z]*[\s\-/.]+20\d{2}\b",

            # APR 30 2026
            r"\b(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|SEPT|OCT|NOV|DEC)"
            r"[A-Z]*[\s\-/.]+\d{1,2}(?:,)?[\s\-/.]+20\d{2}\b",

            # time
            r"\b(?:[01]?\d|2[0-3])[:.]\d{2}(?::\d{2})?\s*(?:AM|PM)?\b",

            # 1600 / 2359 when accompanied by shipping date words
            r"\b(?:[01]\d|2[0-3])[0-5]\d\s*(?:HRS?|HOURS?)?\b",
        ]

        return any(
            re.search(
                pattern,
                value,
                re.IGNORECASE,
            )
            for pattern
            in patterns
        )

    @classmethod
    def _looks_like_value_line(
        cls,
        line: str,
        prefer_datetime=False,
    ) -> bool:

        if not line:
            return False

        if cls._is_boilerplate(
            line
        ):
            return False

        if prefer_datetime:

            if cls._looks_like_datetime(
                line
            ):
                return True

            # A date and time can be split over two lines; keep short
            # non-label fragments so they can be joined.
            return (
                len(
                    line
                ) <= 55
                and not cls._is_known_label_line(
                    line
                )
            )

        return (
            len(
                line
            ) <= 160
            and not cls._is_known_label_line(
                line
            )
        )

    @classmethod
    def _extract_alias_entries(
        cls,
        lines,
        aliases,
        continuation_lines=1,
        prefer_datetime=False,
    ):

        entries = []

        for index, line in enumerate(
            lines
        ):

            obvious_label, obvious_value = (
                cls._split_obvious_label_value(
                    line
                )
            )

            score = cls._best_alias_score(
                obvious_label,
                aliases,
            )

            # Always try prefix removal. This is essential for compact
            # no-colon layouts such as:
            #   CARRIER SAMPLE SHIPPING
            #   POL CAT LAI
            #   GATE-IN DEADLINE 20-SEP-2026 18:00
            prefix_remainder = cls._remove_alias_prefix(
                line,
                aliases,
            )

            remainder = ""

            if prefix_remainder:

                remainder = prefix_remainder
                score = max(
                    score,
                    0.91,
                )

            elif (
                score >= 0.84
                and obvious_value
            ):

                remainder = obvious_value

            else:

                # A genuine label-only line may use the next line as value.
                # Require a strong match to avoid document titles/prose.
                normalized_line = cls._normalize_label(
                    line
                )

                if normalized_line in {
                    "BOOKING CONFIRMATION",
                    "BOOKING ACKNOWLEDGEMENT",
                    "BOOKING ACKNOWLEDGMENT",
                    "BOOKING NOTE",
                }:

                    score = 0.0

                else:

                    score = cls._best_alias_score(
                        line,
                        aliases,
                    )

                    if score < 0.94:
                        score = 0.0

            if score < 0.84:
                continue

            values = []

            cleaned_remainder = cls._clean_business_value(
                remainder
            )

            if cleaned_remainder:

                values.append(
                    cleaned_remainder
                )

            # If a deadline already has both date and time on the same
            # line, do not absorb following labels as continuation text.
            same_line_complete_datetime = False

            if (
                prefer_datetime
                and remainder
                and cls._looks_like_datetime(
                    remainder
                )
            ):

                has_date = bool(
                    re.search(
                        r"20\d{2}[/.\-]\d{1,2}[/.\-]\d{1,2}"
                        r"|\d{1,2}[/.\-]\d{1,2}[/.\-](?:20)?\d{2}"
                        r"|\d{1,2}[\s\-/.]+"
                        r"(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|SEPT|OCT|NOV|DEC)",
                        remainder,
                        re.IGNORECASE,
                    )
                )

                has_time = bool(
                    re.search(
                        r"\b(?:[01]?\d|2[0-3])[:.]\d{2}"
                        r"(?::\d{2})?\s*(?:AM|PM)?\b"
                        r"|\b(?:[01]\d|2[0-3])[0-5]\d\b",
                        remainder,
                        re.IGNORECASE,
                    )
                )

                same_line_complete_datetime = (
                    has_date
                    and has_time
                )

            # If same-line value is absent or a date/time is wrapped,
            # inspect nearby lines.
            continuation_limit = (
                0
                if same_line_complete_datetime
                else continuation_lines
            )

            for next_index in range(
                index + 1,
                min(
                    len(
                        lines
                    ),
                    index
                    + 1
                    + continuation_limit,
                ),
            ):

                raw_candidate = lines[
                    next_index
                ].strip()

                candidate = cls._clean_business_value(
                    raw_candidate
                )

                if not candidate:
                    continue

                if cls._is_known_label_line(
                    raw_candidate
                ):

                    break

                if not cls._looks_like_value_line(
                    candidate,
                    prefer_datetime=(
                        prefer_datetime
                    ),
                ):

                    break

                # For ordinary fields, once a same-line value exists,
                # only append clearly wrapped location/text fragments.
                if (
                    values
                    and not prefer_datetime
                    and len(
                        candidate
                    ) > 90
                ):

                    break

                values.append(
                    candidate
                )

                if (
                    prefer_datetime
                    and cls._looks_like_datetime(
                        "\n".join(
                            values
                        )
                    )
                ):

                    # Date and time could have been split; once both are
                    # plausibly present, do not absorb unrelated text.
                    combined = " ".join(
                        values
                    )

                    has_time = bool(
                        re.search(
                            r"\b(?:[01]?\d|2[0-3])"
                            r"[:.]\d{2}"
                            r"(?:[:.]\d{2})?"
                            r"\s*(?:AM|PM)?\b",
                            combined,
                            re.I,
                        )
                        or re.search(
                            r"\b(?!(?:19|20)\d{2}\b)(?:[01]\d|2[0-3])[0-5]\d\b",
                            combined,
                        )
                    )

                    if has_time:
                        break

            value = "\n".join(
                values
            ).strip()

            if (
                prefer_datetime
                and value
            ):

                # Remove transport-channel/helper text that sometimes sits
                # between the label and actual date/time, e.g.
                # "via EDI/WEB/APP :2026/04/29 11:59".
                date_start = re.search(
                    r"20\d{2}[/.-]\d{1,2}[/.-]\d{1,2}"
                    r"|\d{1,2}[/.-]\d{1,2}[/.-](?:20)?\d{2}"
                    r"|\d{1,2}[\s\-/.]+"
                    r"(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|SEPT|OCT|NOV|DEC)",
                    value,
                    re.IGNORECASE,
                )

                if (
                    date_start
                    and date_start.start() > 0
                ):

                    value = value[
                        date_start.start():
                    ].strip(
                        " :;-–—"
                    )

            if value:

                entries.append(
                    {
                        "index":
                            index,

                        "value":
                            value,

                        "line":
                            line,

                        "score":
                            score,
                    }
                )

        return cls._dedupe_entries(
            entries
        )

    @staticmethod
    def _first_value(
        entries,
    ) -> str:

        return (
            entries[0]["value"]
            if entries
            else ""
        )

    @classmethod
    def _dedupe_entries(
        cls,
        entries,
    ):

        output = []
        seen = set()

        for entry in entries:

            key = cls._normalize_label(
                entry[
                    "value"
                ]
            )

            if key in seen:
                continue

            seen.add(
                key
            )

            output.append(
                entry
            )

        return output

    @classmethod
    def _same_value(
        cls,
        left,
        right,
    ) -> bool:

        return (
            cls._normalize_label(
                left
            )
            == cls._normalize_label(
                right
            )
        )

    # ======================================================
    # Confirmation metadata
    # ======================================================

    @classmethod
    def _extract_revision(
        cls,
        text,
        lines,
    ) -> str:

        patterns = [
            r"BOOKING\s+CONFIRMATION\s*/\s*REVISE"
            r"\s*[:#\-]?\s*([A-Z0-9._/-]+)",

            r"BOOKING\s+CONFIRMATION\s*/\s*REVISION"
            r"\s*[:#\-]?\s*([A-Z0-9._/-]+)",

            r"\bREV(?:ISION|ISE)?"
            r"\s*(?:NO|NUMBER|#)?"
            r"\s*[:#\-]?\s*([A-Z0-9._/-]+)",
        ]

        for pattern in patterns:

            match = re.search(
                pattern,
                text,
                re.IGNORECASE,
            )

            if match:

                return match.group(
                    1
                ).strip()

        return ""

    @classmethod
    def _extract_confirmation_date(
        cls,
        text,
        lines,
    ) -> str:

        patterns = [
            r"BOOKING\s+CONFIRMATION[^\n]{0,100}?"
            r"\bDATE\s*[:\-]\s*([^*\n]+)",

            r"CONFIRMATION\s+DATE"
            r"\s*[:\-]?\s*([^\n]+)",

            r"BOOKING\s+DATE"
            r"\s*[:\-]?\s*([^\n]+)",

            r"ISSUE\s+DATE"
            r"\s*[:\-]?\s*([^\n]+)",

            r"ISSUED\s+DATE"
            r"\s*[:\-]?\s*([^\n]+)",
        ]

        for pattern in patterns:

            match = re.search(
                pattern,
                text,
                re.IGNORECASE,
            )

            if match:

                return match.group(
                    1
                ).strip()

        return ""

    @classmethod
    def _extract_shared_identifiers(
        cls,
        text,
        result,
    ):

        # Works when Booking No and another field share one printed line.
        booking_patterns = [
            r"(?:BOOKING|BKG|BK)\s*"
            r"(?:NO(?:\.)?|NUMBER|#|REF(?:ERENCE)?)"
            r"(?=\s|:|\-|$)"
            r"\s*[:\-]?\s*"
            r"([A-Z0-9][A-Z0-9._/-]*)",

            r"RESERVATION\s*"
            r"(?:NO(?:\.)?|NUMBER|#|REF(?:ERENCE)?)"
            r"(?=\s|:|\-|$)"
            r"\s*[:\-]?\s*"
            r"([A-Z0-9][A-Z0-9._/-]*)",
        ]

        # Strong identifier regexes override weaker fuzzy guesses.
        # This prevents document titles such as "BOOKING CONFIRMATION"
        # from ever becoming the booking number.
        for pattern in booking_patterns:

            match = re.search(
                pattern,
                text,
                re.IGNORECASE,
            )

            if match:

                result[
                    "carrier_booking_no"
                ] = match.group(
                    1
                ).strip()

                break

        match = re.search(
            r"(?:APPLICATION|APP|REQUEST)\s*"
            r"(?:NO\.?|NUMBER|#)"
            r"\s*[:\-]?\s*"
            r"([A-Z0-9][A-Z0-9._/-]*)",
            text,
            re.IGNORECASE,
        )

        if match:

            result[
                "application_no"
            ] = match.group(
                1
            ).strip()

    # ======================================================
    # ETA context
    # ======================================================

    @classmethod
    def _eta_is_pol_context(
        cls,
        lines,
        index,
    ) -> bool:

        start = max(
            0,
            index - 5,
        )

        end = min(
            len(
                lines
            ),
            index + 3,
        )

        context = cls._normalize_label(
            " ".join(
                lines[
                    start:end
                ]
            )
        )

        pol_terms = [
            "PORT OF LOADING",
            "LOADING PORT",
            "POL",
            "POL TERMINAL",
            "DEPARTURE TERMINAL",
        ]

        pod_terms = [
            "PORT OF DISCHARGE",
            "DISCHARGE PORT",
            "POD",
            "FINAL DESTINATION",
            "PLACE OF DELIVERY",
        ]

        has_pol = any(
            cls._normalize_label(
                term
            ) in context
            for term
            in pol_terms
        )

        has_pod = any(
            cls._normalize_label(
                term
            ) in context
            for term
            in pod_terms
        )

        return (
            has_pol
            and not has_pod
        )

    # ======================================================
    # Semantic deadline fallback
    # ======================================================

    @classmethod
    def _line_deadline_value(
        cls,
        lines,
        index,
    ) -> str:

        line = lines[
            index
        ]

        _, obvious_value = (
            cls._split_obvious_label_value(
                line
            )
        )

        if (
            obvious_value
            and cls._looks_like_datetime(
                obvious_value
            )
        ):

            return obvious_value.strip()

        # Try to remove a text label and keep a date/time tail.
        date_patterns = [
            r"(20\d{2}[/.\-]\d{1,2}[/.\-]\d{1,2}"
            r"(?:\s+(?:[01]?\d|2[0-3])[:.]\d{2}"
            r"(?::\d{2})?\s*(?:AM|PM)?)?.*)$",

            r"(\d{1,2}[/.\-]\d{1,2}[/.\-](?:20)?\d{2}"
            r"(?:\s+(?:[01]?\d|2[0-3])[:.]\d{2}"
            r"(?::\d{2})?\s*(?:AM|PM)?)?.*)$",

            r"(\d{1,2}[\s\-/.]+"
            r"(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|SEPT|OCT|NOV|DEC)"
            r"[A-Z]*[\s\-/.]+20\d{2}"
            r"(?:\s+(?:[01]?\d|2[0-3])[:.]?\d{0,2}"
            r"\s*(?:AM|PM|HRS?)?)?.*)$",
        ]

        for pattern in date_patterns:

            match = re.search(
                pattern,
                line,
                re.IGNORECASE,
            )

            if match:

                return match.group(
                    1
                ).strip()

        values = []

        for next_index in range(
            index + 1,
            min(
                len(
                    lines
                ),
                index + 4,
            ),
        ):

            candidate = lines[
                next_index
            ].strip()

            if cls._is_known_label_line(
                candidate
            ):
                break

            if cls._is_boilerplate(
                candidate
            ):
                break

            if (
                cls._looks_like_datetime(
                    candidate
                )
                or (
                    values
                    and len(
                        candidate
                    ) <= 25
                )
            ):

                values.append(
                    candidate
                )

                if cls._looks_like_datetime(
                    " ".join(
                        values
                    )
                ):
                    # Keep one extra short line only if it likely carries
                    # a split time.
                    if (
                        next_index + 1
                        < len(
                            lines
                        )
                        and len(
                            lines[
                                next_index + 1
                            ]
                        ) <= 15
                        and not cls._is_known_label_line(
                            lines[
                                next_index + 1
                            ]
                        )
                    ):
                        extra = lines[
                            next_index + 1
                        ]

                        if re.search(
                            r"\d",
                            extra,
                        ):
                            values.append(
                                extra
                            )

                    break

        return "\n".join(
            values
        ).strip()

    @classmethod
    def _semantic_deadline_class(
        cls,
        line,
    ):

        normalized = cls._normalize_label(
            line
        )

        if not normalized:
            return None

        # Explicit schedule fields.
        if re.search(
            r"\bETD\b",
            normalized,
        ) or (
            "ESTIMATED" in normalized
            and "DEPARTURE" in normalized
        ):

            return "etd"

        if (
            "POL ETA" in normalized
            or "ETA POL" in normalized
            or (
                "ARRIVAL" in normalized
                and "POL" in normalized
            )
        ):

            return "pol_eta"

        if re.search(
            r"\bETA\b",
            normalized,
        ) or (
            "ESTIMATED" in normalized
            and "ARRIVAL" in normalized
        ):

            return "eta"

        # Deadlines need a deadline-ish word.
        has_deadline_word = any(
            cls._normalize_label(
                word
            ) in normalized
            for word
            in cls.DEADLINE_WORDS
        )

        if not has_deadline_word:
            return None

        if (
            "VGM" in normalized
            or "VERIFIED GROSS MASS"
            in normalized
        ):

            return "vgm_cutoff"

        if (
            re.search(
                r"\bSI\b",
                normalized,
            )
            or "SHIPPING INSTRUCTION"
            in normalized
        ):

            return "si_cutoff"

        if (
            "DOCUMENTATION"
            in normalized
            or re.search(
                r"\bDOC\b",
                normalized,
            )
            or "BL INSTRUCTION"
            in normalized
            or "BILL OF LADING INSTRUCTION"
            in normalized
        ):

            return (
                "documentation_cutoff"
            )

        cy_terms = [
            "CY",
            "CARGO",
            "TERMINAL",
            "GATE",
            "CONTAINER",
            "FCL",
            "LADEN",
            "FULL CONTAINER",
            "PORT",
        ]

        if any(
            re.search(
                r"\b"
                + re.escape(
                    cls._normalize_label(
                        term
                    )
                )
                + r"\b",
                normalized,
            )
            for term
            in cy_terms
        ):

            return "cy_cutoff"

        # Generic "CUT OFF DATE/TIME" with no qualifier is generally the
        # cargo/CY cut-off in booking confirmations.
        if (
            "CUTOFF" in normalized
            or "CLOSING" in normalized
        ):

            return "cy_cutoff"

        return None

    @classmethod
    def _semantic_deadline_fallback(
        cls,
        lines,
        result,
    ):

        for index, line in enumerate(
            lines
        ):

            field_name = (
                cls._semantic_deadline_class(
                    line
                )
            )

            if not field_name:
                continue

            if result.get(
                field_name
            ):
                continue

            value = cls._line_deadline_value(
                lines,
                index,
            )

            if not value:
                continue

            if field_name == "eta":

                if cls._eta_is_pol_context(
                    lines,
                    index,
                ) and not result.get(
                    "pol_eta"
                ):

                    result[
                        "pol_eta"
                    ] = value

                else:

                    result[
                        "eta"
                    ] = value

            else:

                result[
                    field_name
                ] = value

    # ======================================================
    # Other deadlines - never silently discard unknown ones
    # ======================================================

    @classmethod
    def _extract_other_deadlines(
        cls,
        lines,
        result,
    ) -> str:

        known_values = {
            cls._normalize_label(
                result.get(
                    key,
                    "",
                )
            )
            for key in [
                "cy_cutoff",
                "vgm_cutoff",
                "si_cutoff",
                "documentation_cutoff",
                "pol_eta",
                "etd",
                "eta",
            ]
            if result.get(
                key
            )
        }

        output = []

        for index, line in enumerate(
            lines
        ):

            normalized = cls._normalize_label(
                line
            )

            if not normalized:
                continue

            if cls._is_boilerplate(
                line
            ):
                continue

            deadlineish = any(
                cls._normalize_label(
                    word
                ) in normalized
                for word
                in cls.DEADLINE_WORDS
            )

            hinted = any(
                re.search(
                    r"\b"
                    + re.escape(
                        cls._normalize_label(
                            hint
                        )
                    )
                    + r"\b",
                    normalized,
                )
                for hint
                in cls.OTHER_DEADLINE_HINTS
                if cls._normalize_label(
                    hint
                )
            )

            if not (
                deadlineish
                and hinted
            ):
                continue

            value = cls._line_deadline_value(
                lines,
                index,
            )

            if not value:
                continue

            normalized_value = (
                cls._normalize_label(
                    value
                )
            )

            if (
                normalized_value
                in known_values
            ):
                continue

            # Do not repeat a known canonical deadline label in
            # Other Deadlines.
            known_class = (
                cls._semantic_deadline_class(
                    line
                )
            )

            if (
                known_class
                in {
                    "cy_cutoff",
                    "vgm_cutoff",
                    "si_cutoff",
                    "documentation_cutoff",
                    "etd",
                    "eta",
                    "pol_eta",
                }
                and result.get(
                    known_class
                )
                and cls._same_value(
                    result[
                        known_class
                    ],
                    value,
                )
            ):

                continue

            label, _ = (
                cls._split_obvious_label_value(
                    line
                )
            )

            label = label.strip()

            if not label:
                label = line.strip()

            # If the entire line contains both label and date, keep a
            # shortened label before the date.
            if cls._looks_like_datetime(
                line
            ):

                date_match = re.search(
                    r"(?=20\d{2}[/.\-]"
                    r"|\d{1,2}[/.\-]\d{1,2}[/.\-]"
                    r"|\d{1,2}\s+"
                    r"(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|SEPT|OCT|NOV|DEC))",
                    line,
                    re.IGNORECASE,
                )

                if date_match:

                    label = line[
                        :date_match.start()
                    ].strip(
                        " :-–—"
                    )

            output.append(
                f"{label}: {value}"
            )

        # Preserve order and uniqueness.
        unique = []
        seen = set()

        for value in output:

            key = cls._normalize_label(
                value
            )

            if key in seen:
                continue

            seen.add(
                key
            )

            unique.append(
                value
            )

        return "\n".join(
            unique
        )

    # ======================================================
    # Container QTY / TYPE
    # ======================================================

    @classmethod
    def _extract_qty_type(
        cls,
        lines,
    ) -> str:

        aliases = [
            "QTY/TYPE",
            "QTY / TYPE",
            "QUANTITY/TYPE",
            "QUANTITY / TYPE",
            "CONTAINER QTY/TYPE",
            "CONTAINER QTY TYPE",
            "EQUIPMENT",
            "EQUIPMENT TYPE",
            "CONTAINER TYPE",
        ]

        entries = cls._extract_alias_entries(
            lines,
            aliases,
            continuation_lines=4,
        )

        if entries:

            first = entries[
                0
            ][
                "value"
            ]

            # If the generic extractor swallowed a table heading plus the
            # actual equipment row, pick the row that starts with quantity
            # and a common container size/type pattern.
            first_lines = [
                part.strip()
                for part in str(
                    first
                ).splitlines()
                if part.strip()
            ]

            equipment_pattern = re.compile(
                r"^\s*\d+\s*"
                r"(?:X|x|/)?\s*"
                r"(?:20|40|45)"
                r"(?:'|FT|HC|HQ|GP|DV|RF|RH|OT|FR|\s)"
                r".*$",
                re.IGNORECASE,
            )

            for candidate in first_lines:

                if equipment_pattern.match(
                    candidate
                ):

                    return candidate.strip()

            # A table heading can be captured instead of the actual row.
            index = entries[
                0
            ][
                "index"
            ]

            for candidate in lines[
                index + 1:
                index + 8
            ]:

                if re.match(
                    r"^[=\-_\s]+$",
                    candidate,
                ):
                    continue

                if equipment_pattern.match(
                    candidate
                ):

                    return candidate.strip()

            return first.strip()

        # Fallback for common equipment lines:
        # "1 x 40HC", "2 /20' STANDARD DRY", "1X40'GP"
        for line in lines:

            if re.match(
                r"^\s*\d+\s*"
                r"(?:X|x|/)\s*"
                r"(?:20|40|45)"
                r"(?:'|\s)?"
                r".{0,50}$",
                line,
                re.IGNORECASE,
            ):

                return line.strip()

        return ""
