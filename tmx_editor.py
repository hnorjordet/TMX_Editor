#!/usr/bin/env python3
"""
TMX Editor - Analysis and Editing Tool for TMX Translation Memory Files

Interactive tool for cleaning, filtering, and manipulating TMX files.

Usage:
  python3 tmx_editor.py                        # Interactive mode (prompts for file)
  python3 tmx_editor.py file.tmx               # Interactive mode with file
  python3 tmx_editor.py --merge                 # Merge all TMX files in current directory
  python3 tmx_editor.py --merge /path/to/dir    # Merge all TMX files in specified directory
  python3 tmx_editor.py --dedup file.tmx        # Remove exact duplicates
  python3 tmx_editor.py --clean file.tmx        # Remove duplicates + empty segments
  python3 tmx_editor.py --csv file.tmx          # Export to CSV
  python3 tmx_editor.py --strip-tags file.tmx   # Strip inline formatting tags
  python3 tmx_editor.py --gui file.tmx          # Retro TUI (Norton Commander style)

Features:
- Remove exact duplicates (keep first occurrence)
- Fuzzy duplicate detection and removal (configurable threshold)
- Remove empty/missing segments
- Strip inline formatting tags
- Filter and export TUs by criteria (language, date, regex)
- Export to CSV
- Merge multiple TMX files (batch: all files in a directory)

Uses only Python standard library.
"""

import xml.etree.ElementTree as ET
import re
import os
import csv
import copy
import io
import sys
import argparse
import glob as globmod
from datetime import datetime
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional, Tuple, List, Dict


class TMXEditor:
    """
    Parses, analyzes, edits, and writes TMX files.
    Retains the full ElementTree for in-place modification.
    """

    INLINE_TAGS = {'bpt', 'ept', 'it', 'ph', 'hi', 'ut', 'sub'}

    def __init__(self):
        self.tree: Optional[ET.ElementTree] = None
        self.root: Optional[ET.Element] = None
        self.file_path: Optional[str] = None
        self.source_lang: str = ""
        self.target_lang: str = ""
        self.encoding: str = "utf-8"
        self.original_doctype: Optional[str] = None

    # ──────────────────────────────────────────────
    # Loading and parsing
    # ──────────────────────────────────────────────

    def load(self, file_path: str) -> None:
        """Load a TMX file, preserving encoding and DOCTYPE."""
        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        self.file_path = file_path

        # Read raw header to capture encoding and DOCTYPE
        with open(file_path, 'rb') as f:
            raw_header = f.read(4096)

        # Detect encoding from XML declaration
        try:
            header_text = raw_header.decode('utf-8')
        except UnicodeDecodeError:
            header_text = raw_header.decode('latin-1')

        enc_match = re.search(r'encoding=["\']([^"\']+)["\']', header_text)
        if enc_match:
            self.encoding = enc_match.group(1).lower()

        # Capture DOCTYPE declaration (ElementTree discards it)
        doctype_match = re.search(r'(<!DOCTYPE\s+[^>]+>)', header_text)
        if doctype_match:
            self.original_doctype = doctype_match.group(1)

        # Register namespace so xml:lang serializes correctly
        ET.register_namespace('xml', 'http://www.w3.org/XML/1998/namespace')

        # Parse the tree
        try:
            self.tree = ET.parse(file_path)
            self.root = self.tree.getroot()
        except ET.ParseError as e:
            raise Exception(f"Error parsing TMX file: {e}")

        # Detect language pair
        self.source_lang, self.target_lang = self._detect_language_pair()

        tu_count = len(self.root.findall('.//tu'))
        print(f"Loaded: {Path(file_path).name}")
        print(f"  TUs: {tu_count:,}")
        print(f"  Languages: {self.source_lang} -> {self.target_lang}")

    def _detect_language_pair(self) -> Tuple[str, str]:
        """Detect source and target languages from TMX header and TUVs."""
        header_src_lang = None
        header = self.root.find('.//header')
        if header is not None:
            header_src_lang = header.get('srclang', '').lower() or None

        # Collect languages from TUVs (sample first 20 TUs)
        tuvs = self.root.findall('.//tuv')
        languages = set()
        for tuv in tuvs[:40]:  # 40 TUVs ~ 20 TUs
            lang = (tuv.get('{http://www.w3.org/XML/1998/namespace}lang') or
                    tuv.get('xml:lang') or
                    tuv.get('lang'))
            if lang:
                languages.add(lang.lower())

        if len(languages) < 2 and len(languages) == 1:
            return list(languages)[0], "unknown"
        if len(languages) < 1:
            return "unknown", "unknown"

        if header_src_lang and header_src_lang in languages:
            source_lang = header_src_lang
            target_lang = next(l for l in sorted(languages) if l != source_lang)
        else:
            sorted_langs = sorted(languages)
            source_lang, target_lang = sorted_langs[0], sorted_langs[1]

        return source_lang, target_lang

    def _get_body(self) -> ET.Element:
        """Get the <body> element from the TMX tree."""
        body = self.root.find('body')
        if body is None:
            body = self.root.find('.//body')
        if body is None:
            raise Exception("No <body> element found in TMX file")
        return body

    def _get_seg_text(self, seg: ET.Element) -> str:
        """Extract plain text from a <seg> element, including text inside inline tags."""
        if seg is None:
            return ""
        return ''.join(seg.itertext()).strip()

    def _get_tu_texts(self, tu: ET.Element) -> Tuple[Optional[str], Optional[str]]:
        """
        Extract (source_text, target_text) from a TU element.
        Returns (None, None) if the TU structure is invalid.
        """
        tuvs = tu.findall('tuv')
        if len(tuvs) < 2:
            return None, None

        source_tuv = None
        target_tuv = None

        for tuv in tuvs:
            tuv_lang = (tuv.get('{http://www.w3.org/XML/1998/namespace}lang') or
                        tuv.get('xml:lang') or
                        tuv.get('lang') or '').lower()

            if tuv_lang == self.source_lang or (source_tuv is None and target_tuv is None):
                source_tuv = tuv
            elif tuv_lang == self.target_lang or target_tuv is None:
                target_tuv = tuv

        if source_tuv is None:
            source_tuv = tuvs[0]
        if target_tuv is None:
            target_tuv = tuvs[1] if len(tuvs) > 1 else tuvs[0]

        source_seg = source_tuv.find('seg')
        target_seg = target_tuv.find('seg')

        source_text = self._get_seg_text(source_seg)
        target_text = self._get_seg_text(target_seg)

        return source_text, target_text

    # ──────────────────────────────────────────────
    # TMX writing
    # ──────────────────────────────────────────────

    def save(self, output_path: str) -> str:
        """
        Write the current tree to a TMX file.
        Preserves DOCTYPE and encoding from the original file.
        """
        ET.register_namespace('xml', 'http://www.w3.org/XML/1998/namespace')

        buffer = io.BytesIO()
        self.tree.write(
            buffer,
            encoding=self.encoding,
            xml_declaration=True,
            short_empty_elements=False
        )
        raw = buffer.getvalue()

        # Inject DOCTYPE if the original had one
        if self.original_doctype:
            decoded = raw.decode(self.encoding)
            insert_pos = decoded.find('?>')
            if insert_pos != -1:
                insert_pos += 2
                decoded = decoded[:insert_pos] + '\n' + self.original_doctype + decoded[insert_pos:]
                raw = decoded.encode(self.encoding)

        with open(output_path, 'wb') as f:
            f.write(raw)

        return output_path

    def _generate_output_path(self, suffix: str) -> str:
        """Generate output filename: {original}_{suffix}_{timestamp}.tmx"""
        p = Path(self.file_path)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        new_name = f"{p.stem}{suffix}_{timestamp}{p.suffix}"
        return str(p.parent / new_name)

    # ──────────────────────────────────────────────
    # Operation 1: Remove exact duplicates
    # ──────────────────────────────────────────────

    def remove_exact_duplicates(self) -> Dict:
        """
        Remove exact duplicate TUs, keeping only the first occurrence.
        Comparison: normalized(source) + normalized(target), case-insensitive.
        """
        body = self._get_body()
        all_tus = list(body.findall('tu'))
        total_before = len(all_tus)

        seen_keys = set()
        to_remove = []
        duplicate_examples = []

        for tu in all_tus:
            source_text, target_text = self._get_tu_texts(tu)
            if source_text is None:
                continue

            norm_source = ' '.join(source_text.lower().split())
            norm_target = ' '.join(target_text.lower().split())
            key = f"{norm_source}|||{norm_target}"

            if key in seen_keys:
                to_remove.append(tu)
                if len(duplicate_examples) < 10:
                    duplicate_examples.append({
                        'source': source_text[:80],
                        'target': target_text[:80]
                    })
            else:
                seen_keys.add(key)

        for tu in to_remove:
            body.remove(tu)

        return {
            'removed_count': len(to_remove),
            'unique_count': total_before - len(to_remove),
            'total_before': total_before,
            'examples': duplicate_examples
        }

    # ──────────────────────────────────────────────
    # Operation 2: Fuzzy duplicate detection
    # ──────────────────────────────────────────────

    def find_fuzzy_duplicates(self, threshold: float = 0.85) -> List[Dict]:
        """
        Find TUs with similar source text using SequenceMatcher.
        Returns groups of similar TUs for user review.
        """
        body = self._get_body()
        all_tus = list(body.findall('tu'))

        # Extract text data, skip invalid TUs
        tu_data = []
        for i, tu in enumerate(all_tus):
            src, tgt = self._get_tu_texts(tu)
            if src:
                tu_data.append((i + 1, tu, src, tgt or ""))

        # Deduplicate by exact source match (only keep unique sources)
        seen_exact = {}
        unique_tus = []
        for item in tu_data:
            norm = ' '.join(item[2].lower().split())
            if norm not in seen_exact:
                seen_exact[norm] = True
                unique_tus.append(item)

        n = len(unique_tus)
        if n > 50000:
            print(f"  Warning: {n:,} unique TUs. Fuzzy matching may take a long time.")
            print(f"  Consider using a higher threshold to speed things up.")

        # Sort by source text length for length-ratio pruning
        unique_tus.sort(key=lambda x: len(x[2]))

        matched = [False] * n
        groups = []

        print(f"  Comparing {n:,} unique source segments...")

        for i in range(n):
            if matched[i]:
                continue

            if (i + 1) % 5000 == 0:
                print(f"  Processed {i + 1:,}/{n:,} segments...")

            group_similar = []
            len_i = len(unique_tus[i][2])

            for j in range(i + 1, n):
                if matched[j]:
                    continue

                len_j = len(unique_tus[j][2])

                # Length-ratio pruning
                if len_i > 0 and len_j > len_i / threshold:
                    break  # All subsequent are even longer

                ratio = SequenceMatcher(
                    None,
                    unique_tus[i][2].lower(),
                    unique_tus[j][2].lower()
                ).ratio()

                if ratio >= threshold:
                    matched[j] = True
                    group_similar.append({
                        'tu_number': unique_tus[j][0],
                        'tu_element': unique_tus[j][1],
                        'source': unique_tus[j][2],
                        'target': unique_tus[j][3],
                        'similarity': round(ratio * 100, 1)
                    })

            if group_similar:
                groups.append({
                    'representative_tu': unique_tus[i][0],
                    'representative_source': unique_tus[i][2],
                    'representative_target': unique_tus[i][3],
                    'similar_tus': group_similar
                })

        return groups

    def remove_fuzzy_duplicates(self, groups: List[Dict]) -> Dict:
        """Remove fuzzy duplicates identified by find_fuzzy_duplicates()."""
        body = self._get_body()
        removed = 0

        for group in groups:
            for similar in group['similar_tus']:
                tu_elem = similar.get('tu_element')
                if tu_elem is not None:
                    try:
                        body.remove(tu_elem)
                        removed += 1
                    except ValueError:
                        pass  # Already removed

        return {'removed_count': removed}

    # ──────────────────────────────────────────────
    # Operation 3: Remove empty/missing segments
    # ──────────────────────────────────────────────

    def remove_empty_segments(self) -> Dict:
        """Remove TUs where source or target is empty/missing."""
        body = self._get_body()
        all_tus = list(body.findall('tu'))
        total_before = len(all_tus)

        to_remove = []
        by_type = defaultdict(int)

        for tu in all_tus:
            tuvs = tu.findall('tuv')

            if len(tuvs) < 2:
                to_remove.append(tu)
                by_type['missing_tuv'] += 1
                continue

            source_text, target_text = self._get_tu_texts(tu)

            if source_text is None:
                to_remove.append(tu)
                by_type['invalid_structure'] += 1
                continue

            if not source_text and not target_text:
                to_remove.append(tu)
                by_type['both_empty'] += 1
            elif not source_text:
                to_remove.append(tu)
                by_type['empty_source'] += 1
            elif not target_text:
                to_remove.append(tu)
                by_type['empty_target'] += 1

        for tu in to_remove:
            body.remove(tu)

        return {
            'removed_count': len(to_remove),
            'remaining_count': total_before - len(to_remove),
            'total_before': total_before,
            'by_type': dict(by_type)
        }

    # ──────────────────────────────────────────────
    # Operation 4: Strip inline formatting tags
    # ──────────────────────────────────────────────

    def strip_inline_tags(self) -> Dict:
        """Remove inline formatting tags from all <seg> elements, keeping text."""
        segments_modified = 0
        tags_removed = 0

        for seg in self.root.iter('seg'):
            children = list(seg)
            if not children:
                continue

            # Collect full text content (including text inside tags)
            full_text = ''.join(seg.itertext())

            # Count tags being removed
            tag_count = sum(1 for _ in seg.iter() if _ is not seg)

            # Preserve seg's own attributes
            attribs = dict(seg.attrib)

            # Clear and rebuild with plain text
            seg.clear()
            seg.attrib.update(attribs)
            seg.text = full_text

            segments_modified += 1
            tags_removed += tag_count

        return {
            'segments_modified': segments_modified,
            'tags_removed': tags_removed
        }

    # ──────────────────────────────────────────────
    # Operation 5: Filter and export
    # ──────────────────────────────────────────────

    def filter_tus(self,
                   source_pattern: str = None,
                   target_pattern: str = None,
                   date_from: str = None,
                   date_to: str = None,
                   invert: bool = False) -> List[ET.Element]:
        """
        Find TUs matching given criteria.

        Args:
            source_pattern: Regex pattern for source text
            target_pattern: Regex pattern for target text
            date_from: Minimum creation date (YYYYMMDD format)
            date_to: Maximum creation date (YYYYMMDD format)
            invert: If True, return TUs that do NOT match

        Returns: list of matching TU elements
        """
        body = self._get_body()
        matching = []

        src_re = re.compile(source_pattern, re.IGNORECASE) if source_pattern else None
        tgt_re = re.compile(target_pattern, re.IGNORECASE) if target_pattern else None

        for tu in body.findall('tu'):
            source_text, target_text = self._get_tu_texts(tu)
            if source_text is None:
                continue

            match = True

            if src_re and not src_re.search(source_text):
                match = False
            if tgt_re and not tgt_re.search(target_text or ""):
                match = False

            if date_from or date_to:
                creation_date = tu.get('creationdate', '')
                # TMX dates are typically YYYYMMDDTHHMMSSZ
                date_part = creation_date[:8] if creation_date else ''
                if date_from and date_part < date_from:
                    match = False
                if date_to and date_part > date_to:
                    match = False

            if invert:
                match = not match

            if match:
                matching.append(tu)

        return matching

    def export_filtered(self, tu_elements: List[ET.Element], output_path: str) -> str:
        """Create a new TMX file containing only the specified TUs."""
        # Deep-copy the tree
        new_tree = copy.deepcopy(self.tree)
        new_root = new_tree.getroot()

        # Find body and clear it
        body = new_root.find('body')
        if body is None:
            body = new_root.find('.//body')

        # Remove all existing TUs
        for tu in list(body.findall('tu')):
            body.remove(tu)

        # Map original TU elements to their copies
        # Since we deep-copied, we need to re-add from original elements (deep-copy them)
        for tu in tu_elements:
            body.append(copy.deepcopy(tu))

        # Write using a temporary editor-like approach
        ET.register_namespace('xml', 'http://www.w3.org/XML/1998/namespace')

        buf = io.BytesIO()
        new_tree.write(buf, encoding=self.encoding, xml_declaration=True,
                       short_empty_elements=False)
        raw = buf.getvalue()

        if self.original_doctype:
            decoded = raw.decode(self.encoding)
            insert_pos = decoded.find('?>')
            if insert_pos != -1:
                insert_pos += 2
                decoded = decoded[:insert_pos] + '\n' + self.original_doctype + decoded[insert_pos:]
                raw = decoded.encode(self.encoding)

        with open(output_path, 'wb') as f:
            f.write(raw)

        return output_path

    # ──────────────────────────────────────────────
    # Operation 6: CSV export
    # ──────────────────────────────────────────────

    def export_to_csv(self, output_path: str, include_metadata: bool = True) -> str:
        """Export all TUs to a CSV file (UTF-8 with BOM for Excel)."""
        body = self._get_body()

        headers = ['TU_Number', 'Source_Language', 'Source_Text',
                   'Target_Language', 'Target_Text']
        if include_metadata:
            headers.extend(['Creation_Date', 'Change_Date'])

        with open(output_path, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(headers)

            for i, tu in enumerate(body.findall('tu'), 1):
                source_text, target_text = self._get_tu_texts(tu)
                if source_text is None:
                    source_text = ""
                if target_text is None:
                    target_text = ""

                row = [i, self.source_lang, source_text,
                       self.target_lang, target_text]

                if include_metadata:
                    row.append(tu.get('creationdate', ''))
                    row.append(tu.get('changedate', ''))

                writer.writerow(row)

        return output_path

    # ──────────────────────────────────────────────
    # Operation 7: Merge TMX files
    # ──────────────────────────────────────────────

    def merge_from(self, other_path: str,
                   duplicate_strategy: str = 'skip') -> Dict:
        """
        Merge another TMX file into the currently loaded one.

        Args:
            other_path: Path to the TMX file to merge
            duplicate_strategy:
                'skip'      - keep existing, ignore incoming duplicate
                'replace'   - replace existing with incoming
                'keep_both' - keep both versions
        """
        other_editor = TMXEditor()
        other_editor.load(other_path)

        body = self._get_body()
        other_body = other_editor._get_body()

        # Build lookup of existing source+target pairs
        existing_pairs = set()
        existing_sources = {}  # normalized_source -> tu_element

        for tu in body.findall('tu'):
            src, tgt = self._get_tu_texts(tu)
            if src is None:
                continue
            norm_src = ' '.join(src.lower().split())
            norm_tgt = ' '.join((tgt or "").lower().split())
            existing_pairs.add(f"{norm_src}|||{norm_tgt}")
            existing_sources[norm_src] = tu

        added = 0
        skipped = 0
        replaced = 0

        for tu in other_body.findall('tu'):
            src, tgt = other_editor._get_tu_texts(tu)
            if src is None:
                continue

            norm_src = ' '.join(src.lower().split())
            norm_tgt = ' '.join((tgt or "").lower().split())
            pair_key = f"{norm_src}|||{norm_tgt}"

            # Exact same source+target already exists
            if pair_key in existing_pairs:
                skipped += 1
                continue

            # Same source, different target
            if norm_src in existing_sources:
                if duplicate_strategy == 'skip':
                    skipped += 1
                    continue
                elif duplicate_strategy == 'replace':
                    old_tu = existing_sources[norm_src]
                    body.remove(old_tu)
                    body.append(copy.deepcopy(tu))
                    existing_sources[norm_src] = tu
                    replaced += 1
                elif duplicate_strategy == 'keep_both':
                    body.append(copy.deepcopy(tu))
                    added += 1
            else:
                body.append(copy.deepcopy(tu))
                existing_pairs.add(pair_key)
                existing_sources[norm_src] = tu
                added += 1

        return {
            'added': added,
            'skipped': skipped,
            'replaced': replaced,
            'total_after': len(body.findall('tu'))
        }

    # ──────────────────────────────────────────────
    # Statistics
    # ──────────────────────────────────────────────

    def get_statistics(self) -> Dict:
        """Get current statistics about the loaded TMX."""
        body = self._get_body()
        all_tus = body.findall('tu')
        total = len(all_tus)

        empty_count = 0
        tagged_segments = 0

        for tu in all_tus:
            src, tgt = self._get_tu_texts(tu)
            if not src or not tgt:
                empty_count += 1

            # Check for inline tags
            for seg in tu.iter('seg'):
                if list(seg):
                    tagged_segments += 1

        # Count exact duplicates (without removing)
        seen = set()
        duplicate_count = 0
        for tu in all_tus:
            src, tgt = self._get_tu_texts(tu)
            if src is None:
                continue
            key = f"{' '.join(src.lower().split())}|||{' '.join((tgt or '').lower().split())}"
            if key in seen:
                duplicate_count += 1
            else:
                seen.add(key)

        return {
            'total_tus': total,
            'source_lang': self.source_lang,
            'target_lang': self.target_lang,
            'empty_segments': empty_count,
            'exact_duplicates': duplicate_count,
            'segments_with_tags': tagged_segments,
            'file': Path(self.file_path).name
        }


# ══════════════════════════════════════════════════
# Interactive CLI
# ══════════════════════════════════════════════════

def _confirm(prompt: str) -> bool:
    """Ask for y/n confirmation."""
    response = input(prompt).strip().lower()
    return response in ('y', 'yes', 'ja', 'j')


def _print_separator():
    print("-" * 60)


def _handle_remove_duplicates(editor: TMXEditor) -> bool:
    """Handle menu option 1: Remove exact duplicates."""
    print("\n  Removing exact duplicates...")
    result = editor.remove_exact_duplicates()
    print(f"\n  Result:")
    print(f"    TUs before:  {result['total_before']:,}")
    print(f"    Removed:     {result['removed_count']:,}")
    print(f"    Remaining:   {result['unique_count']:,}")

    if result['examples']:
        print(f"\n  Examples of removed duplicates:")
        for i, ex in enumerate(result['examples'][:5], 1):
            print(f"    {i}. \"{ex['source']}\"")
            print(f"       \"{ex['target']}\"")

    return result['removed_count'] > 0


def _handle_fuzzy_duplicates(editor: TMXEditor) -> bool:
    """Handle menu option 2: Find and optionally remove fuzzy duplicates."""
    threshold_str = input("  Similarity threshold (0-100, default 85): ").strip()
    if threshold_str:
        try:
            threshold = float(threshold_str) / 100.0
            if not 0 < threshold <= 1:
                print("  Invalid threshold. Using 85%.")
                threshold = 0.85
        except ValueError:
            print("  Invalid input. Using 85%.")
            threshold = 0.85
    else:
        threshold = 0.85

    print(f"\n  Finding fuzzy duplicates (threshold: {threshold*100:.0f}%)...")
    groups = editor.find_fuzzy_duplicates(threshold=threshold)

    if not groups:
        print("  No fuzzy duplicates found.")
        return False

    total_similar = sum(len(g['similar_tus']) for g in groups)
    print(f"\n  Found {len(groups)} groups with {total_similar} fuzzy duplicates.")

    # Show groups
    for i, group in enumerate(groups[:20], 1):
        print(f"\n  Group {i}: (keeping TU #{group['representative_tu']})")
        print(f"    Representative: \"{group['representative_source'][:70]}\"")
        for sim in group['similar_tus'][:3]:
            print(f"    {sim['similarity']}% match: \"{sim['source'][:70]}\"")
        if len(group['similar_tus']) > 3:
            print(f"    ... and {len(group['similar_tus']) - 3} more")

    if len(groups) > 20:
        print(f"\n  ... and {len(groups) - 20} more groups")

    if _confirm(f"\n  Remove {total_similar} fuzzy duplicates? (y/n): "):
        result = editor.remove_fuzzy_duplicates(groups)
        print(f"  Removed {result['removed_count']:,} fuzzy duplicates.")
        return result['removed_count'] > 0

    print("  Skipped removal.")
    return False


def _handle_remove_empty(editor: TMXEditor) -> bool:
    """Handle menu option 3: Remove empty/missing segments."""
    print("\n  Removing empty/missing segments...")
    result = editor.remove_empty_segments()
    print(f"\n  Result:")
    print(f"    TUs before:  {result['total_before']:,}")
    print(f"    Removed:     {result['removed_count']:,}")
    print(f"    Remaining:   {result['remaining_count']:,}")

    if result['by_type']:
        print(f"\n  Breakdown:")
        type_labels = {
            'missing_tuv': 'Missing TUV element',
            'invalid_structure': 'Invalid TU structure',
            'both_empty': 'Both source & target empty',
            'empty_source': 'Empty source text',
            'empty_target': 'Empty target text'
        }
        for issue_type, count in sorted(result['by_type'].items(),
                                        key=lambda x: x[1], reverse=True):
            label = type_labels.get(issue_type, issue_type)
            print(f"    {label}: {count:,}")

    return result['removed_count'] > 0


def _handle_strip_tags(editor: TMXEditor) -> bool:
    """Handle menu option 4: Strip inline formatting tags."""
    print("\n  Stripping inline formatting tags...")
    result = editor.strip_inline_tags()
    print(f"\n  Result:")
    print(f"    Segments modified: {result['segments_modified']:,}")
    print(f"    Tags removed:     {result['tags_removed']:,}")
    return result['segments_modified'] > 0


def _handle_filter_export(editor: TMXEditor) -> bool:
    """Handle menu option 5: Filter and export TUs."""
    print("\n  Filter TUs by criteria (leave blank to skip):")
    source_pattern = input("    Source text regex pattern: ").strip() or None
    target_pattern = input("    Target text regex pattern: ").strip() or None
    date_from = input("    Date from (YYYYMMDD, e.g. 20230101): ").strip() or None
    date_to = input("    Date to (YYYYMMDD, e.g. 20241231): ").strip() or None

    invert = _confirm("    Invert filter (export NON-matching TUs)? (y/n): ")

    try:
        matching = editor.filter_tus(
            source_pattern=source_pattern,
            target_pattern=target_pattern,
            date_from=date_from,
            date_to=date_to,
            invert=invert
        )
    except re.error as e:
        print(f"  Invalid regex pattern: {e}")
        return False

    print(f"\n  Found {len(matching):,} matching TUs.")

    if not matching:
        return False

    output_path = editor._generate_output_path('_filtered')
    custom_path = input(f"  Output file [{output_path}]: ").strip()
    if custom_path:
        output_path = custom_path

    saved = editor.export_filtered(matching, output_path)
    print(f"  Exported to: {saved}")
    return False  # Doesn't modify the main tree


def _handle_csv_export(editor: TMXEditor) -> bool:
    """Handle menu option 6: Export to CSV."""
    output_path = editor._generate_output_path('_export').replace('.tmx', '.csv')
    custom_path = input(f"  Output file [{output_path}]: ").strip()
    if custom_path:
        output_path = custom_path

    include_meta = _confirm("  Include metadata (dates)? (y/n): ")
    saved = editor.export_to_csv(output_path, include_metadata=include_meta)
    print(f"  Exported to: {saved}")
    return False  # Doesn't modify the main tree


def _handle_merge(editor: TMXEditor) -> bool:
    """Handle menu option 7: Merge another TMX file."""
    other_path = input("  Path to TMX file to merge: ").strip().strip('"').strip("'")
    if not other_path or not os.path.isfile(other_path):
        print("  File not found.")
        return False

    print("\n  Duplicate handling strategy:")
    print("    1. Skip (keep existing, ignore incoming) [default]")
    print("    2. Replace (incoming overwrites existing)")
    print("    3. Keep both")
    strategy_choice = input("  Select (1-3): ").strip()
    strategy_map = {'1': 'skip', '2': 'replace', '3': 'keep_both'}
    strategy = strategy_map.get(strategy_choice, 'skip')

    print(f"\n  Merging with strategy: {strategy}...")
    result = editor.merge_from(other_path, duplicate_strategy=strategy)
    print(f"\n  Result:")
    print(f"    Added:    {result['added']:,}")
    print(f"    Skipped:  {result['skipped']:,}")
    print(f"    Replaced: {result['replaced']:,}")
    print(f"    Total TUs after merge: {result['total_after']:,}")

    return result['added'] > 0 or result['replaced'] > 0


def _handle_statistics(editor: TMXEditor):
    """Handle menu option 8: Show statistics."""
    stats = editor.get_statistics()
    print(f"\n  File: {stats['file']}")
    print(f"  Languages: {stats['source_lang']} -> {stats['target_lang']}")
    _print_separator()
    print(f"  Total TUs:              {stats['total_tus']:,}")
    print(f"  Empty/missing segments: {stats['empty_segments']:,}")
    print(f"  Exact duplicates:       {stats['exact_duplicates']:,}")
    print(f"  Segments with tags:     {stats['segments_with_tags']:,}")


def _find_tmx_files(directory: str) -> List[str]:
    """Find all .tmx files in a directory (non-recursive)."""
    pattern = os.path.join(directory, '*.tmx')
    # Also check .TMX (case-insensitive on case-sensitive filesystems)
    files = globmod.glob(pattern)
    files += [f for f in globmod.glob(os.path.join(directory, '*.TMX')) if f not in files]
    files.sort()
    return files


def _batch_merge(directory: str, output: str = None,
                 duplicate_strategy: str = 'skip') -> None:
    """Merge all TMX files in a directory into one."""
    tmx_files = _find_tmx_files(directory)

    if not tmx_files:
        print(f"No TMX files found in: {directory}")
        sys.exit(1)

    print(f"Found {len(tmx_files)} TMX files in: {directory}")
    for i, f in enumerate(tmx_files, 1):
        print(f"  {i}. {Path(f).name}")

    if len(tmx_files) < 2:
        print("Need at least 2 TMX files to merge.")
        sys.exit(1)

    # Load the first file as base
    editor = TMXEditor()
    print(f"\nLoading base file: {Path(tmx_files[0]).name}")
    editor.load(tmx_files[0])

    total_added = 0
    total_skipped = 0
    total_replaced = 0

    # Merge remaining files one by one
    for tmx_path in tmx_files[1:]:
        print(f"\nMerging: {Path(tmx_path).name}...")
        result = editor.merge_from(tmx_path, duplicate_strategy=duplicate_strategy)
        total_added += result['added']
        total_skipped += result['skipped']
        total_replaced += result['replaced']
        print(f"  +{result['added']:,} added, {result['skipped']:,} skipped", end="")
        if result['replaced']:
            print(f", {result['replaced']:,} replaced", end="")
        print()

    # Generate output path
    if not output:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output = os.path.join(directory, f"merged_{timestamp}.tmx")

    editor.save(output)

    final_stats = editor.get_statistics()
    print(f"\n{'=' * 60}")
    print(f"Merge complete!")
    print(f"  Files merged:    {len(tmx_files)}")
    print(f"  TUs added:       {total_added:,}")
    print(f"  TUs skipped:     {total_skipped:,}")
    if total_replaced:
        print(f"  TUs replaced:    {total_replaced:,}")
    print(f"  Total TUs:       {final_stats['total_tus']:,}")
    print(f"  Strategy:        {duplicate_strategy}")
    print(f"  Output:          {output}")


def _batch_operation(file_path: str, operations: List[str], output: str = None) -> None:
    """Run one or more operations non-interactively on a TMX file."""
    editor = TMXEditor()
    editor.load(file_path)

    modifications = False

    for op in operations:
        if op == 'dedup':
            print("\nRemoving exact duplicates...")
            result = editor.remove_exact_duplicates()
            print(f"  Removed {result['removed_count']:,} duplicates "
                  f"({result['total_before']:,} -> {result['unique_count']:,} TUs)")
            if result['removed_count'] > 0:
                modifications = True

        elif op == 'empty':
            print("\nRemoving empty/missing segments...")
            result = editor.remove_empty_segments()
            print(f"  Removed {result['removed_count']:,} empty segments "
                  f"({result['total_before']:,} -> {result['remaining_count']:,} TUs)")
            if result['removed_count'] > 0:
                modifications = True

        elif op == 'strip-tags':
            print("\nStripping inline formatting tags...")
            result = editor.strip_inline_tags()
            print(f"  Modified {result['segments_modified']:,} segments, "
                  f"removed {result['tags_removed']:,} tags")
            if result['segments_modified'] > 0:
                modifications = True

        elif op == 'csv':
            csv_path = output or editor._generate_output_path('_export').replace('.tmx', '.csv')
            print(f"\nExporting to CSV...")
            editor.export_to_csv(csv_path)
            print(f"  Exported to: {csv_path}")
            return  # CSV doesn't need TMX save

    if modifications:
        if not output:
            suffix_parts = []
            if 'dedup' in operations:
                suffix_parts.append('deduped')
            if 'empty' in operations:
                suffix_parts.append('cleaned')
            if 'strip-tags' in operations:
                suffix_parts.append('stripped')
            suffix = '_' + '_'.join(suffix_parts) if suffix_parts else '_edited'
            output = editor._generate_output_path(suffix)

        editor.save(output)
        print(f"\nSaved to: {output}")
    else:
        print("\nNo modifications needed.")


def _interactive_mode(file_path: str = None) -> None:
    """Run the interactive menu."""
    print("=" * 60)
    print("TMX Editor - Translation Memory Editing Tool")
    print("=" * 60)
    print()

    editor = TMXEditor()

    if not file_path:
        file_path = input("Enter path to TMX file: ").strip().strip('"').strip("'")

    if not file_path:
        print("No file specified. Exiting.")
        sys.exit(1)

    try:
        editor.load(file_path)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

    modifications_made = False

    while True:
        print("\n" + "=" * 60)
        print("TMX Editor Menu:")
        print("  1. Remove exact duplicates")
        print("  2. Find fuzzy duplicates")
        print("  3. Remove empty/missing segments")
        print("  4. Strip inline formatting tags")
        print("  5. Filter and export TUs")
        print("  6. Export to CSV")
        print("  7. Merge another TMX file")
        print("  8. Show current statistics")
        print("  9. Save and exit")
        print("  0. Exit without saving")
        _print_separator()

        choice = input("Select operation (0-9): ").strip()

        if choice == '1':
            if _handle_remove_duplicates(editor):
                modifications_made = True

        elif choice == '2':
            if _handle_fuzzy_duplicates(editor):
                modifications_made = True

        elif choice == '3':
            if _handle_remove_empty(editor):
                modifications_made = True

        elif choice == '4':
            if _handle_strip_tags(editor):
                modifications_made = True

        elif choice == '5':
            _handle_filter_export(editor)

        elif choice == '6':
            _handle_csv_export(editor)

        elif choice == '7':
            if _handle_merge(editor):
                modifications_made = True

        elif choice == '8':
            _handle_statistics(editor)

        elif choice == '9':
            if modifications_made:
                output_path = editor._generate_output_path('_edited')
                custom_path = input(f"  Save to [{output_path}]: ").strip()
                if custom_path:
                    output_path = custom_path
                editor.save(output_path)
                print(f"\n  Saved to: {output_path}")
            else:
                print("  No modifications to save.")
            break

        elif choice == '0':
            if modifications_made:
                if not _confirm("  Unsaved changes will be lost. Exit anyway? (y/n): "):
                    continue
            print("  Exiting.")
            break

        else:
            print("  Invalid choice. Please select 0-9.")


def main():
    parser = argparse.ArgumentParser(
        description="TMX Editor - Analysis and Editing Tool for TMX Translation Memory Files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                              Interactive mode
  %(prog)s file.tmx                     Interactive mode with file
  %(prog)s --gui file.tmx               Retro TUI (Norton Commander style)
  %(prog)s --merge                      Merge all TMX files in current directory
  %(prog)s --merge /path/to/tmx/files   Merge all TMX files in specified directory
  %(prog)s --merge --strategy replace   Merge, incoming overwrites existing
  %(prog)s --dedup file.tmx             Remove exact duplicates
  %(prog)s --clean file.tmx             Remove duplicates + empty segments
  %(prog)s --strip-tags file.tmx        Strip inline formatting tags
  %(prog)s --csv file.tmx               Export to CSV
  %(prog)s --dedup --strip-tags f.tmx   Chain multiple operations
  %(prog)s --dedup file.tmx -o out.tmx  Specify output file
"""
    )

    parser.add_argument('file', nargs='?', default=None,
                        help='TMX file to edit (or directory for --merge)')

    # Operation modes
    ops = parser.add_argument_group('batch operations')
    ops.add_argument('--merge', action='store_true',
                     help='Merge all TMX files in a directory into one. '
                          'Uses current directory if no path given.')
    ops.add_argument('--dedup', action='store_true',
                     help='Remove exact duplicates (non-interactive)')
    ops.add_argument('--clean', action='store_true',
                     help='Remove duplicates + empty/missing segments (non-interactive)')
    ops.add_argument('--strip-tags', action='store_true',
                     help='Strip inline formatting tags (non-interactive)')
    ops.add_argument('--csv', action='store_true',
                     help='Export to CSV (non-interactive)')
    ops.add_argument('--gui', action='store_true',
                     help='Launch retro TUI (Norton Commander / Turbo Pascal style)')

    # Options
    parser.add_argument('-o', '--output', default=None,
                        help='Output file path (default: auto-generated)')
    parser.add_argument('--strategy', choices=['skip', 'replace', 'keep_both'],
                        default='skip',
                        help='Duplicate strategy for merge (default: skip)')

    args = parser.parse_args()

    # Determine which mode to run
    has_batch_op = args.merge or args.dedup or args.clean or args.strip_tags or args.csv

    if args.gui:
        # Retro TUI mode
        from tmx_tui import run_tui
        run_tui(file_path=args.file)

    elif args.merge:
        # Merge mode: directory of TMX files
        directory = args.file or os.getcwd()
        if os.path.isfile(directory):
            directory = os.path.dirname(directory)
        if not os.path.isdir(directory):
            print(f"Error: Not a directory: {directory}")
            sys.exit(1)
        _batch_merge(directory, output=args.output, duplicate_strategy=args.strategy)

    elif has_batch_op:
        # Non-interactive batch operation on a single file
        if not args.file:
            parser.error("A TMX file is required for this operation.")

        if not os.path.isfile(args.file):
            print(f"Error: File not found: {args.file}")
            sys.exit(1)

        operations = []
        if args.dedup or args.clean:
            operations.append('dedup')
        if args.clean:
            operations.append('empty')
        if args.strip_tags:
            operations.append('strip-tags')
        if args.csv:
            operations.append('csv')

        _batch_operation(args.file, operations, output=args.output)

    else:
        # Interactive mode
        _interactive_mode(file_path=args.file)


if __name__ == "__main__":
    main()
