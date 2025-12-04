#!/usr/bin/env python3
"""
Fix .po files with newline mismatch errors between msgid and msgstr
"""

import re
import sys
from pathlib import Path

def extract_full_string(lines, start_idx):
    """Extract full msgid or msgstr value including multiline strings"""
    value = ""
    i = start_idx

    while i < len(lines):
        line = lines[i].strip()

        # Match quoted string
        match = re.match(r'"(.*)"', line)
        if match:
            value += match.group(1)
            i += 1
        else:
            break

    return value, i

def fix_po_file(filepath):
    """Fix newline mismatches in a .po file"""
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    fixed_lines = []
    changes_made = 0
    i = 0

    while i < len(lines):
        line = lines[i]

        # Check if this is a msgid line
        if line.startswith('msgid'):
            # Extract full msgid
            msgid_value, next_i = extract_full_string(lines, i + 1)

            # Find corresponding msgstr
            msgstr_idx = next_i
            while msgstr_idx < len(lines) and not lines[msgstr_idx].startswith('msgstr'):
                msgstr_idx += 1

            if msgstr_idx < len(lines):
                # Extract full msgstr
                msgstr_value, after_msgstr = extract_full_string(lines, msgstr_idx + 1)

                # Check newline mismatch
                msgid_ends_with_newline = msgid_value.endswith('\\n')
                msgstr_ends_with_newline = msgstr_value.endswith('\\n')

                if msgid_ends_with_newline != msgstr_ends_with_newline:
                    # Fix the last line of msgstr
                    last_msgstr_line_idx = after_msgstr - 1

                    if last_msgstr_line_idx >= msgstr_idx + 1:
                        last_line = lines[last_msgstr_line_idx]

                        if msgid_ends_with_newline and not msgstr_ends_with_newline:
                            # Add \n before closing quote
                            lines[last_msgstr_line_idx] = last_line.replace('"\n', '\\n"\n')
                            changes_made += 1
                        elif not msgid_ends_with_newline and msgstr_ends_with_newline:
                            # Remove \n before closing quote
                            lines[last_msgstr_line_idx] = last_line.replace('\\n"\n', '"\n')
                            changes_made += 1

        i += 1

    # Write back
    if changes_made > 0:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.writelines(lines)
        print(f"✓ Fixed {changes_made} entries in {filepath.name}")
        return changes_made
    else:
        print(f"  No changes needed in {filepath.name}")
        return 0

def main():
    locale_dir = Path('locale')

    if not locale_dir.exists():
        print("Error: locale/ directory not found")
        sys.exit(1)

    total_fixes = 0
    po_files = list(locale_dir.glob('*.po'))

    print(f"Checking {len(po_files)} .po files...\n")

    for po_file in sorted(po_files):
        fixes = fix_po_file(po_file)
        total_fixes += fixes

    print(f"\n✓ Total: Fixed {total_fixes} entries across all files")

if __name__ == '__main__':
    main()
