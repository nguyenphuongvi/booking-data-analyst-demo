import re


class DocumentAnalyzer:

    FIELD_LABELS = [
        "PACKING LIST",
        "DATE OF BOOKING",
        "BOOKING DATE",
        "DATED",
        "DATE",
        "SHIPPER",
        "EXPORTER",
        "CONSIGNEE",
        "NOTIFY PARTY",
        "NOTIFY",
        "PRODUCT",
        "COMMODITY",
        "DESCRIPTION OF GOODS",
        "DESCRIPTION",
        "PACKING",
        "PACKAGING",
        "QUANTITY",
        "QTY",
        "TOTAL QTY",
        "MARKING",
        "SHIPPING MARK",
        "SHIPPING MARKS",
        "MARKS & NOS",
        "MARKS AND NUMBERS",
    ]

    def analyze(self, text: str) -> dict:
        """
        Analyze ONE uploaded physical file as ONE container.

        Important business rule:
        - 1 uploaded file = 1 container.
        - A file may contain several repeated PACKING LIST pages.
        - Those pages stay inside the SAME container.
        - Pallet breakdown lines from all pages are preserved in order.
        - Duplicate pallet quantities are preserved.

        Example in one file:
            Page 1:
                45 PALLETS OF ...
                01 PALLETS OF ...

            Page 2:
                01 PALLETS OF ...

        Result for the ONE container:
            Total Pallet:
                45 PALLETS
                01 PALLETS
                01 PALLETS
        """

        cleaned_text = self.clean_text(text)

        sections = self.split_packing_list_sections(
            cleaned_text
        )

        if not sections:
            sections = [cleaned_text] if cleaned_text else []

        section_results = [
            self._analyze_cleaned_section(section)
            for section in sections
            if section.strip()
        ]

        if not section_results:
            return self.empty_result()

        combined = self.combine_file_sections(
            section_results
        )

        combined["packing_list_pages"] = len(
            section_results
        )

        # Presentation-only structure.
        # One physical file is still ONE container.
        # Each repeated PACKING LIST page keeps the number of
        # pallet/detail rows that belong to that page.
        presentation_segment_sizes = []

        for section_result in section_results:

            pallet_lines = [
                line.strip()
                for line in str(
                    section_result.get(
                        "total_pallet",
                        "",
                    )
                ).splitlines()
                if line.strip()
            ]

            detail_lines = [
                line.strip()
                for line in str(
                    section_result.get(
                        "packing_details",
                        "",
                    )
                ).splitlines()
                if line.strip()
            ]

            presentation_segment_sizes.append(
                max(
                    len(pallet_lines),
                    len(detail_lines),
                    1,
                )
            )

        combined[
            "presentation_segment_sizes"
        ] = presentation_segment_sizes

        combined["container_pallet_total"] = (
            self.calculate_pallet_total(
                combined.get(
                    "total_pallet",
                    "",
                )
            )
        )

        return combined

    def analyze_sections(self, text: str) -> list[dict]:
        """
        Return page/section-level results for diagnostics only.

        These sections are NOT containers.
        The app should use analyze() for normal booking extraction.
        """

        cleaned_text = self.clean_text(text)

        sections = self.split_packing_list_sections(
            cleaned_text
        )

        results = []

        for section_index, section_text in enumerate(
            sections,
            start=1,
        ):
            extracted = self._analyze_cleaned_section(
                section_text
            )

            extracted["source_section"] = section_index
            extracted["section_pallet_total"] = (
                self.calculate_pallet_total(
                    extracted.get(
                        "total_pallet",
                        "",
                    )
                )
            )

            results.append(extracted)

        return results

    def empty_result(self) -> dict:
        return {
            "date_of_booking": "",
            "shipper": "",
            "consignee": "",
            "notify": "",
            "product": "",
            "total_pallet": "",
            "packing_details": "",
            "quantity": "",
            "marking": "",
            "packing_list_pages": 0,
            "presentation_segment_sizes": [],
            "container_pallet_total": 0,
        }

    def combine_file_sections(
        self,
        section_results: list[dict],
    ) -> dict:
        """
        Combine repeated PACKING LIST pages into ONE container.

        Identity fields normally repeat on each page, so use the first
        non-empty value.

        Product/Quantity/Marking may legitimately vary between pages,
        so preserve page values without collapsing pallet groups.

        Total Pallet and Packing Details ALWAYS preserve every line,
        including duplicate quantities such as 01 + 01.
        """

        def first_non_empty(field: str) -> str:
            for row in section_results:
                value = str(
                    row.get(field, "")
                ).strip()
                if value:
                    return value
            return ""

        def append_all_blocks(field: str) -> str:
            blocks = []

            for row in section_results:
                value = str(
                    row.get(field, "")
                ).strip()

                if value:
                    blocks.append(value)

            return "\n".join(blocks).strip()

        def append_unique_blocks(field: str) -> str:
            blocks = []
            seen = set()

            for row in section_results:
                value = str(
                    row.get(field, "")
                ).strip()

                if not value:
                    continue

                normalized = " ".join(
                    value.upper().split()
                )

                if normalized in seen:
                    continue

                seen.add(normalized)
                blocks.append(value)

            return "\n".join(blocks).strip()

        return {
            "date_of_booking":
                first_non_empty(
                    "date_of_booking"
                ),

            "shipper":
                first_non_empty(
                    "shipper"
                ),

            "consignee":
                first_non_empty(
                    "consignee"
                ),

            "notify":
                first_non_empty(
                    "notify"
                ),

            # If a container file has multiple products/pages,
            # keep the distinct product values.
            "product":
                append_unique_blocks(
                    "product"
                ),

            # Critical: preserve every pallet group in page order.
            # DO NOT deduplicate 01 PALLETS.
            "total_pallet":
                append_all_blocks(
                    "total_pallet"
                ),

            "packing_details":
                append_all_blocks(
                    "packing_details"
                ),

            # Keep page-level quantity blocks so information is not lost.
            "quantity":
                append_all_blocks(
                    "quantity"
                ),

            # Usually repeated, so avoid exact duplicated marking blocks.
            "marking":
                append_unique_blocks(
                    "marking"
                ),
        }

    def _analyze_cleaned_section(
        self,
        text: str,
    ) -> dict:

        packing = self.extract_packing(
            text
        )

        return {
            "date_of_booking":
                self.extract_date(text),

            "shipper":
                self.extract_field(
                    text,
                    [
                        "SHIPPER",
                        "EXPORTER",
                    ],
                    multiline=True,
                ),

            "consignee":
                self.extract_field(
                    text,
                    [
                        "CONSIGNEE",
                    ],
                    multiline=True,
                ),

            "notify":
                self.extract_field(
                    text,
                    [
                        "NOTIFY PARTY",
                        "NOTIFY",
                    ],
                    multiline=True,
                ),

            "product":
                self.extract_field(
                    text,
                    [
                        "PRODUCT",
                        "COMMODITY",
                        "DESCRIPTION OF GOODS",
                        "DESCRIPTION",
                    ],
                    multiline=True,
                ),

            "total_pallet":
                packing[
                    "total_pallet"
                ],

            "packing_details":
                packing[
                    "packing_details"
                ],

            "quantity":
                self.extract_quantity(
                    text
                ),

            "marking":
                self.extract_marking(
                    text
                ),
        }

    def split_packing_list_sections(
        self,
        text: str,
    ) -> list[str]:
        """
        Split repeated PACKING LIST pages inside one file.

        This is only an internal page split.
        It does NOT create extra containers.
        """

        lines = text.splitlines()
        section_starts = []

        for index, line in enumerate(
            lines
        ):

            if re.fullmatch(
                r"PACKING\s+LIST",
                line.strip(),
                re.IGNORECASE,
            ):
                section_starts.append(index)

        if len(section_starts) <= 1:
            return [
                text.strip()
            ] if text.strip() else []

        sections = []

        for position, start_index in enumerate(
            section_starts
        ):

            end_index = (
                section_starts[
                    position + 1
                ]
                if (
                    position + 1
                    < len(section_starts)
                )
                else len(lines)
            )

            section_text = "\n".join(
                lines[
                    start_index:end_index
                ]
            ).strip()

            if section_text:
                sections.append(
                    section_text
                )

        return sections

    def clean_text(
        self,
        text: str,
    ) -> str:

        text = text.replace(
            "\r\n",
            "\n",
        )

        text = text.replace(
            "\r",
            "\n",
        )

        text = text.replace(
            "\f",
            "\n",
        )

        cleaned_lines = []

        for line in text.splitlines():

            line = re.sub(
                r"[ \t]+",
                " ",
                line,
            ).strip()

            if line:
                cleaned_lines.append(
                    line
                )

        return "\n".join(
            cleaned_lines
        )

    def extract_date(
        self,
        text: str,
    ) -> str:

        patterns = [
            r"DATE\s+OF\s+BOOKING\s*[:\-]?\s*([^\n]+)",
            r"BOOKING\s+DATE\s*[:\-]?\s*([^\n]+)",
            r"\bDATED\s*[:\-]?\s*([^\n]+)",
            r"\bDATE\s*[:\-]\s*([^\n]+)",
        ]

        for pattern in patterns:

            match = re.search(
                pattern,
                text,
                re.IGNORECASE,
            )

            if match:
                return (
                    match.group(1)
                    .strip()
                )

        return ""

    def extract_field(
        self,
        text: str,
        labels: list[str],
        multiline: bool = False,
        max_lines: int = 30,
    ) -> str:

        lines = text.splitlines()

        for index, line in enumerate(
            lines
        ):

            for label in labels:

                pattern = (
                    r"^"
                    + re.escape(label)
                    + r"\s*[:\-]?\s*(.*)$"
                )

                match = re.match(
                    pattern,
                    line,
                    re.IGNORECASE,
                )

                if not match:
                    continue

                values = []

                same_line_value = (
                    match.group(1)
                    .strip()
                )

                if same_line_value:

                    values.append(
                        same_line_value
                    )

                    if not multiline:
                        return (
                            same_line_value
                        )

                for next_index in range(
                    index + 1,
                    min(
                        index + 1
                        + max_lines,
                        len(lines),
                    ),
                ):

                    next_line = (
                        lines[next_index]
                        .strip()
                    )

                    if not next_line:
                        continue

                    if self.is_new_field(
                        next_line
                    ):
                        break

                    values.append(
                        next_line
                    )

                    if not multiline:
                        break

                return "\n".join(
                    values
                ).strip()

        return ""

    def is_new_field(
        self,
        line: str,
    ) -> bool:

        for label in self.FIELD_LABELS:

            pattern = (
                r"^"
                + re.escape(label)
                + r"(?:\s|:|\-|$)"
            )

            if re.match(
                pattern,
                line,
                re.IGNORECASE,
            ):
                return True

        return False

    def extract_marking(
        self,
        text: str,
    ) -> str:
        """
        Extract only the useful MARKING / SHIPPING MARK content.

        Footer text such as:
            RESTRICTED
            *** RESTRICTED ***
            RESTRICTED DOCUMENT
            RESTRICTED - INTERNAL USE ONLY

        is NOT part of Marking and must never be returned.
        """

        lines = [
            line.strip()
            for line in text.splitlines()
            if line.strip()
        ]

        if not lines:
            return ""

        labels = [
            "MARKING",
            "SHIPPING MARKS",
            "SHIPPING MARK",
            "MARKS & NOS",
            "MARKS AND NUMBERS",
        ]

        def is_restricted_footer(
            line: str,
        ) -> bool:

            normalized = re.sub(
                r"^[\W_]+|[\W_]+$",
                "",
                line,
            ).strip()

            return bool(
                re.match(
                    r"^RESTRICTED\b",
                    normalized,
                    re.IGNORECASE,
                )
            )

        for index, line in enumerate(
            lines
        ):

            for label in labels:

                match = re.match(
                    (
                        r"^"
                        + re.escape(label)
                        + r"\s*[:\-]?\s*(.*)$"
                    ),
                    line,
                    re.IGNORECASE,
                )

                if not match:
                    continue

                values = []

                same_line_value = (
                    match.group(1)
                    .strip()
                )

                if (
                    same_line_value
                    and not is_restricted_footer(
                        same_line_value
                    )
                ):
                    values.append(
                        same_line_value
                    )

                for next_index in range(
                    index + 1,
                    min(
                        index + 1 + 50,
                        len(lines),
                    ),
                ):

                    next_line = lines[
                        next_index
                    ].strip()

                    if not next_line:
                        continue

                    # "RESTRICTED" is a page/footer classification,
                    # not business data.
                    if is_restricted_footer(
                        next_line
                    ):
                        break

                    if self.is_new_field(
                        next_line
                    ):
                        break

                    values.append(
                        next_line
                    )

                return "\n".join(
                    values
                ).strip()

        return ""

    def extract_quantity(
        self,
        text: str,
    ) -> str:
        """
        Extract the COMPLETE quantity block for one PACKING LIST page.

        Supported examples include:
            QUANTITY TOTAL NET : 13,140.00 KGS
            UNIT PACK : 12 KGS / BOX
            TOTAL GROSS : 14,250.00 KGS

        and documents that omit the QUANTITY heading:
            TOTAL NET WEIGHT : ...
            UNIT PACK : ...
            TOTAL GROSS WEIGHT : ...

        It also handles:
            TOTAL QTY / TOTAL QUANTITY / QTY
            NET WEIGHT / N.W. / NW
            GROSS WEIGHT / G.W. / GW
            wrapped values on following lines

        The parser keeps every line in the quantity section until the next
        real document field/section begins. This prevents UNIT PACK, TOTAL
        GROSS, package counts, or wrapped values from being dropped.
        """

        lines = [
            line.strip()
            for line in text.splitlines()
            if line.strip()
        ]

        if not lines:
            return ""

        explicit_quantity_pattern = re.compile(
            r"^QUANTITY\s*[:\-]?\s*(.*)$",
            re.IGNORECASE,
        )

        # Primary quantity anchors used when the document has no standalone
        # QUANTITY heading.
        quantity_anchor_patterns = [
            re.compile(
                r"^TOTAL\s+NET(?:\s+WEIGHT)?\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"^NET\s+WEIGHT\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"^N\.?\s*W\.?\s*[:\-]?",
                re.IGNORECASE,
            ),
            re.compile(
                r"^NW\s*[:\-]?",
                re.IGNORECASE,
            ),
            re.compile(
                r"^TOTAL\s+(?:QTY|QUANTITY)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"^QTY\s*[:\-]?",
                re.IGNORECASE,
            ),
        ]

        # These labels belong to the next section, not Quantity.
        # They are deliberately broader than FIELD_LABELS because real
        # Packing Lists often put manufacturer/origin/HS-code data between
        # Quantity and Marking.
        stop_labels = [
            "PACKING LIST",
            "DATE OF BOOKING",
            "BOOKING DATE",
            "DATED",
            "DATE",
            "SHIPPER",
            "EXPORTER",
            "CONSIGNEE",
            "NOTIFY PARTY",
            "NOTIFY",
            "PRODUCT",
            "COMMODITY",
            "DESCRIPTION OF GOODS",
            "DESCRIPTION",
            "PACKING",
            "PACKAGING",
            "MARKING",
            "SHIPPING MARK",
            "SHIPPING MARKS",
            "MARKS & NOS",
            "MARKS AND NUMBERS",
            "MANUFACTURER",
            "MANUFACTURED BY",
            "COMPANY NAME",
            "APPEARANCE",
            "H CODE",
            "HS CODE",
            "H.S. CODE",
            "COUNTRY OF ORIGIN",
            "ORIGIN",
            "REMARK",
            "REMARKS",
        ]

        def is_stop_line(
            line: str,
        ) -> bool:

            for label in stop_labels:

                pattern = (
                    r"^"
                    + re.escape(label)
                    + r"(?:\s|:|\-|$)"
                )

                if re.match(
                    pattern,
                    line,
                    re.IGNORECASE,
                ):
                    return True

            return False

        start_index = None
        first_value = ""

        # Prefer an explicit QUANTITY heading.
        for index, line in enumerate(
            lines
        ):

            match = explicit_quantity_pattern.match(
                line
            )

            if not match:
                continue

            start_index = index

            # Keep the useful part after QUANTITY.
            # Example:
            # "QUANTITY TOTAL NET : 100 KGS"
            # -> "TOTAL NET : 100 KGS"
            first_value = (
                match.group(1)
                .strip()
            )

            break

        # Fallback: documents may start directly with TOTAL NET / N.W. etc.
        if start_index is None:

            for index, line in enumerate(
                lines
            ):

                if any(
                    pattern.match(
                        line
                    )
                    for pattern
                    in quantity_anchor_patterns
                ):

                    start_index = index
                    first_value = line
                    break

        if start_index is None:
            return ""

        values = []

        if first_value:
            values.append(
                first_value
            )

        # Capture the whole section, including wrapped continuation lines.
        for next_index in range(
            start_index + 1,
            min(
                start_index + 1 + 80,
                len(lines),
            ),
        ):

            next_line = lines[
                next_index
            ].strip()

            if not next_line:
                continue

            if is_stop_line(
                next_line
            ):
                break

            # A second explicit QUANTITY heading means a new quantity block.
            # This normally belongs to another page/section.
            if explicit_quantity_pattern.match(
                next_line
            ):
                break

            values.append(
                next_line
            )

        # If the explicit QUANTITY line itself had no value, the lines after
        # it become the block. If it had a value, that value stays first.
        return "\n".join(
            values
        ).strip()

    def pallet_number_to_int(
        self,
        value: str,
    ) -> int:

        cleaned = (
            str(value)
            .replace(",", "")
            .strip()
        )

        try:
            return int(cleaned)
        except ValueError:
            return 0

    def calculate_pallet_total(
        self,
        total_pallet: str,
    ) -> int:
        """
        Internal check only.

        The UI/export still keeps the individual pallet breakdown lines.
        """

        total = 0

        for line in str(
            total_pallet
        ).splitlines():

            match = re.match(
                r"^\s*(\d[\d,]*)\s+PALLETS?\b",
                line,
                re.IGNORECASE,
            )

            if match:
                total += (
                    self.pallet_number_to_int(
                        match.group(1)
                    )
                )

        return total

    def strip_packing_label(
        self,
        line: str,
    ) -> str:

        return re.sub(
            r"^(?:PACKING|PACKAGING)\s*[:\-]?\s*",
            "",
            line.strip(),
            flags=re.IGNORECASE,
        ).strip()

    def extract_packing(
        self,
        text: str,
    ) -> dict:
        """
        Extract pallet breakdown for ONE PACKING LIST page.

        Prefer each "xx PALLETS OF ..." line for displayed breakdown.
        Preserve order and duplicates.
        """

        standalone_groups = []
        detail_groups = []

        for original_line in text.splitlines():

            original_line = (
                original_line.strip()
            )

            if not original_line:
                continue

            line = self.strip_packing_label(
                original_line
            )

            if not line:
                continue

            standalone_match = re.match(
                r"^(\d[\d,]*)\s*"
                r"(?:PALLET|PALLETS|PLT|PLTS)"
                r"\s*([./\\-]*)\s*$",
                line,
                re.IGNORECASE,
            )

            if standalone_match:

                standalone_groups.append(
                    {
                        "number_text":
                            standalone_match
                            .group(1)
                            .strip(),

                        "suffix":
                            standalone_match
                            .group(2)
                            .strip(),
                    }
                )

                continue

            detail_match = re.match(
                r"^(\d[\d,]*)\s*"
                r"(?:PALLET|PALLETS|PLT|PLTS)"
                r"\s+OF\s+(.+?)\s*$",
                line,
                re.IGNORECASE,
            )

            if detail_match:

                number_text = (
                    detail_match
                    .group(1)
                    .strip()
                )

                description = (
                    detail_match
                    .group(2)
                    .strip()
                )

                detail_groups.append(
                    {
                        "number_text":
                            number_text,

                        "detail":
                            (
                                f"{number_text} "
                                f"PALLETS OF "
                                f"{description}"
                            ),
                    }
                )

        total_pallet_lines = []

        if detail_groups:

            for group in detail_groups:

                # Deliberately preserve duplicates.
                total_pallet_lines.append(
                    f"{group['number_text']} "
                    f"PALLETS"
                )

        else:

            for group in standalone_groups:

                total_pallet_lines.append(
                    f"{group['number_text']} "
                    f"PALLETS"
                )

        packing_detail_lines = [
            group["detail"]
            for group in detail_groups
        ]

        return {
            "total_pallet":
                "\n".join(
                    total_pallet_lines
                ),

            "packing_details":
                "\n".join(
                    packing_detail_lines
                ),
        }
