# Originally written by Eric Martel (emartel@gmail.com / www.ericmartel.com)
# Improved by Wade Brainerd (wadetb@gmail.com / www.wadeb.com)

import sublime
import sublime_plugin

import fnmatch, os, re, sys
from math import *

# http://stackoverflow.com/questions/11301138/how-to-check-if-variable-is-string-with-python-2-and-3-compatibility
try:
    isinstance("", basestring)
    def isstr(s):
        return isinstance(s, basestring)
except NameError:
    def isstr(s):
        return isinstance(s, str)

directory = os.path.dirname(os.path.realpath(__file__))
sys.path.append(directory)

from tinynumpy import tinynumpy

try:
    import numpy
except ImportError:
    print("=== NumPy disabled, using TinyNumPy instead ===")
    print("To enable cell evaluation using the full NumPy, download NumPy from:")
    print("    https://pypi.python.org/pypi/numpy")
    print("and install it into Sublime Text's Packages directory.")
    print("For information on the features and limitations of TinyNumPy, visit:")
    print("    https://github.com/wadetb/tinynumpy")
    print("======================")
    numpy = tinynumpy

class SortDirection:
    Ascending = 1
    Descending = 2

class CSVValue:
    def __init__(self, text, first_char_index=0, last_char_index=0):
        self.text = text
        self.first_char_index = first_char_index
        self.last_char_index = last_char_index

    def AsFloat(self):
        try:
            return True, float(self.text)
        except ValueError:
            return False, None

    def Compare(self, other):
        a_is_float, a_float = self.AsFloat()
        b_is_float, b_float = other.AsFloat()

        if a_is_float and b_is_float:
            return a_float - b_float

        if self.text > other.text:
            return 1
        if self.text < other.text:
            return -1
        return 0

    def __lt__(self, other): return self.Compare(other) < 0
    def __eq__(self, other): return self.Compare(other) == 0

class CSVMatrix:
    def __init__(self, view):
        self.rows = []
        self.num_columns = 0
        self.valid = False
        self.view = view

        self.settings = sublime.load_settings('AdvancedCSV.sublime-settings')

        self.ChooseDelimiter()

        self.auto_quote = self.GetViewOrUserSetting( 'auto_quote', True )

    def GetViewOrUserSetting(self, name, default):
        if self.view.settings().has(name):
            return self.view.settings().get(name)
        else:
            return self.settings.get(name, default)

    def ChooseDelimiter(self):
        self.delimiter = None

        # Highest priority: per-view saved setting (CSV -> Set Delimiter).
        if self.view.settings().has('delimiter'):
            self.delimiter = self.view.settings().get('delimiter')

        # Second highest priority: filename-based matching
        if not self.delimiter:
            filename = self.view.file_name()

            if filename:
                self.delimiter_mapping = self.settings.get('delimiter_mapping', {})
                for k, v in self.delimiter_mapping.items():
                    if fnmatch.fnmatch(filename, k):
                        self.delimiter = v
                        break

        # Final priority: user or system setting, fallback to comma. 
        if not self.delimiter:
            self.delimiter = self.settings.get('delimiter', ',')

        # Special case for recognizing '\t' for tabs.
        if self.delimiter == '\\t':
            self.delimiter = '\t'

        if not isstr(self.delimiter) or len(self.delimiter) != 1:
            print("'{0}' is not a valid delimiter, reverting to ','.".format(self.delimiter))
            self.delimiter = ','

        print("Using delimiter: '{0}'.".format(self.delimiter))

    def AddRow(self, row):
        self.rows.append(row)

    def Finalize(self):
        if not len(self.rows):
            return

        self.num_columns = 0
        for row in self.rows:
            if len(row) > self.num_columns:
                self.num_columns = len(row)

        self.valid = True

    @staticmethod
    def GetCellValue(row, column_index):
        try:
            return row[column_index]
        except IndexError:
            return CSVValue('')

    def SortByColumn(self, column_index, direction, use_header):
        class Compare:
            def __init__(self, row): self.value = CSVMatrix.GetCellValue(row, column_index)
            def __lt__(self, other): return self.value < other.value
            def __eq__(self, other): return self.value == other.value

        reverse = direction == SortDirection.Descending

        if use_header:
            self.rows[1:] = sorted(self.rows[1:], key=lambda row: Compare(row), reverse=reverse)
        else:
            self.rows.sort(key=lambda row: Compare(row), reverse=reverse)

    def InsertColumn(self, column_index):
        for row in self.rows:
            if column_index <= len(row):
                row.insert(column_index, CSVValue(''))

    def DeleteColumn(self, column_index):
        for row in self.rows:
            if column_index < len(row):
                row.pop(column_index)

    def DeleteTrailingColumns(self, column_index):
        for row in self.rows:
            last_column_index = 0

            for column_index, value in enumerate(row):
                if len(value.text.strip()) > 0:
                    last_column_index = column_index

            first_empty_column_index = last_column_index + 1
            del row[first_empty_column_index:]

    def SelectColumn(self, column_index, view):
        view.sel().clear()

        for row_index, row in enumerate(self.rows):
            if column_index < len(row):
                value = row[column_index]
                a = view.text_point(row_index, value.first_char_index)
                b = view.text_point(row_index, value.last_char_index)

                region = sublime.Region(a, b)
                view.sel().add(region)

    @staticmethod
    def SaveSelection(view):
        saved_selection = []

        for region in view.sel():
            a_row, a_col = view.rowcol(region.a)
            b_row, b_col = view.rowcol(region.b)

            rowcol_region = (a_row, a_col, b_row, b_col)

            saved_selection.append(rowcol_region)

        return saved_selection

    @staticmethod
    def RestoreSelection(view, saved_selection):
        view.sel().clear()

        for rowcol_region in saved_selection:
            a = view.text_point(rowcol_region[0], rowcol_region[1])
            b = view.text_point(rowcol_region[2], rowcol_region[3])

            region = sublime.Region(a, b)
            view.sel().add(region)

    def QuoteText(self, text):
        if not self.auto_quote:
            return text
        if self.delimiter in text or '"' in text:
            return '"' + text.replace('"', '""') + '"'
        else:
            return text

    def MeasureColumns(self):
        self.column_widths = [0] * self.num_columns

        for row in self.rows:
            for column_index, value in enumerate(row):
                text = self.QuoteText(value.text)
                width = len(text)

                if width > self.column_widths[column_index]:
                    self.column_widths[column_index] = width

    def Format(self):
        output = ''

        for row_index, row in enumerate(self.rows):
            row_text = ''

            for column_index, value in enumerate(row):
                quoted_text = self.QuoteText(value.text)

                row_text += quoted_text

                if column_index < len(row) - 1:
                    row_text += self.delimiter

            output += row_text

            if row_index < len(self.rows) - 1:
                output += '\n'

        return output

    def FormatCompacted(self):
        output = ''

        for row_index, row in enumerate(self.rows):
            row_text = ''

            for column_index, value in enumerate(row):
                quoted_trimmed_text = self.QuoteText(value.text.strip())

                row_text += quoted_trimmed_text

                if column_index < len(row) - 1:
                    row_text += self.delimiter

            output += row_text

            if row_index < len(self.rows) - 1:
                output += '\n'

        return output

    def FormatExpanded(self):
        self.MeasureColumns()

        output = ''

        for row_index, row in enumerate(self.rows):
            row_text = ''

            # A blank line (including the empty row after the final newline) stays empty.
            if len(row) == 1 and row[0].text == '':
                output += '\n' if row_index < len(self.rows) - 1 else ''
                continue

            for column_index, value in enumerate(row):
                quoted_text = self.QuoteText(value.text)

                column_width = self.column_widths[column_index]

                quoted_padded_text = quoted_text.ljust(column_width)

                row_text += quoted_padded_text

                if column_index < len(row) - 1:
                    row_text += self.delimiter

            output += row_text

            if row_index < len(self.rows) - 1:
                output += '\n'

        return output

    def ParseRow(self, row):
        columns = []

        currentword = ''
        first_char_index = 0
        insidequotes = False

        char_index = 0
        while char_index < len(row):
            char = row[char_index]

            if insidequotes:
                if char == '"':
                    if char_index < len(row) - 1 and row[char_index + 1] == '"':
                        if self.auto_quote:
                            currentword += '"'
                        else:
                            currentword += '""'
                        char_index += 2
                        continue
                     
                    insidequotes = False
                    if not self.auto_quote:
                        currentword += char
                        
                else:
                    currentword += char

            else:
                if char == '"':
                    insidequotes = True
                    if not self.auto_quote:
                        currentword += char

                elif char == self.delimiter:
                    columns.append(CSVValue(currentword, first_char_index, char_index))
                    currentword = ''
                    first_char_index = char_index + 1

                else:
                    currentword += char

            char_index += 1

        columns.append(CSVValue(currentword, first_char_index, char_index))

        return columns

    @staticmethod
    def FromView(view):
        matrix = CSVMatrix(view)

        text = view.substr(sublime.Region(0, view.size()))

        for line in text.split("\n"):
            row = matrix.ParseRow(line)

            matrix.AddRow(row)

        matrix.Finalize()

        return matrix

    def GetColumnIndexFromCursor(self, view):
        selection = view.sel()[0]

        row_index, col_index = view.rowcol(selection.begin())

        if row_index < len(self.rows):
            row = self.rows[row_index]

            for column_index, value in enumerate(row):
                if value.first_char_index > col_index:
                    return column_index - 1

            return len(row) - 1

        else:
            return 0

    EXPRESSION_RE = re.compile(r'''
        \s*
        (\[
            (?P<row_begin_mod>[+-])?
            (?P<row_begin>\d+)?
            (?P<row_delim>:)?
            (?P<row_end_mod>[+-])?
            (?P<row_end>\d+)?
            (?P<comma>,)?
            (?P<column_begin_mod>[+-])?
            (?P<column_begin>\d+)?
            (?P<column_delim>:)?
            (?P<column_end_mod>[+-])?
            (?P<column_end>\d+)?
        \])?
        \s*
        (?P<direction>[<>v^])?
        \s*
        =
        \s*
        (?P<expression>.+)
        ''', re.VERBOSE)

    def ApplyModifier(self, value, mod, base_value):
        if mod == '+':
            return base_value + value
        elif mod == '-':
            return base_value - value
        else:
            return value

    def GetCoordinateRange(self, begin_mod, begin, delim, end_mod, end, base_value):
        if delim:
            if begin is None:
                begin = 0
            else:
                begin = self.ApplyModifier(int(begin), begin_mod, base_value)
            if end is None:
                end = len(self.rows)
            else:
                end = self.ApplyModifier(int(end), end_mod, base_value)
        else:
            if begin is None:
                begin = base_value
                end = base_value + 1
            else:
                begin = self.ApplyModifier(int(begin), begin_mod, base_value)
                end = begin + 1

        return (begin, end)

    def GetRowColumnCoordinateRange(self, coordinate_match, base_row_index, base_column_index):
        row_begin_mod = coordinate_match.group('row_begin_mod')
        row_begin = coordinate_match.group('row_begin')
        row_delim = coordinate_match.group('row_delim')
        row_end_mod = coordinate_match.group('row_end_mod')
        row_end = coordinate_match.group('row_end')

        row_range = self.GetCoordinateRange(row_begin_mod, row_begin, row_delim, row_end_mod, row_end, base_row_index)

        column_begin_mod = coordinate_match.group('column_begin_mod')
        column_begin = coordinate_match.group('column_begin')
        column_delim = coordinate_match.group('column_delim')
        column_end_mod = coordinate_match.group('column_end_mod')
        column_end = coordinate_match.group('column_end')

        column_range = self.GetCoordinateRange(column_begin_mod, column_begin, column_delim, column_end_mod, column_end, base_column_index)

        return (row_range[0], row_range[1], column_range[0], column_range[1])

    def ApplyDirectionOffsetToRange(self, direction_match, coord_range):
        direction = direction_match.group('direction')

        if direction == '^':
            return (coord_range[0] - 1, coord_range[1] - 1, coord_range[2], coord_range[3])
        elif direction == 'v':
            return (coord_range[0] + 1, coord_range[1] + 1, coord_range[2], coord_range[3])
        elif direction == '<':
            return (coord_range[0], coord_range[1], coord_range[2] - 1, coord_range[3] - 1)
        elif direction == '>':
            return (coord_range[0], coord_range[1], coord_range[2] + 1, coord_range[3] + 1)
        else:
            return coord_range

    def EvaluateExpressionCell(self, m, row_index, column_index, value, expression_match):
        target_range = self.GetRowColumnCoordinateRange(expression_match, row_index, column_index)

        target_range = self.ApplyDirectionOffsetToRange(expression_match, target_range)

        expression = expression_match.group('expression')

        # Expand sheet for target range.
        while target_range[1] >= len(self.rows):
            self.rows.append([])
        while target_range[3] >= len(self.column_widths):
            self.column_widths.append(0)

        for target_row_index in range(target_range[0], target_range[1]):
            for target_column_index in range(target_range[2], target_range[3]):
                try:
                    l = {}
                    l['m'] = m
                    l['row'] = target_row_index
                    l['col'] = target_column_index
                    l['frow'] = row_index
                    l['fcol'] = column_index
                    result = eval(str(expression), None, l)

                except Exception as e:
                    print("Exception '{0}' evaluating expression for target cell [{1}, {2}].".format(str(e), target_row_index, target_column_index))
                    result = str(e)

                try:
                    row = self.rows[target_row_index]

                    while target_column_index >= len(row):
                        row.append(CSVValue(''.ljust(self.column_widths[len(row)])))

                    target_value = self.rows[target_row_index][target_column_index]
                    target_value.text = str(result).ljust(len(target_value.text))

                except IndexError:
                    print("Invalid expression target cell [{0}, {1}].".format(target_row_index, target_column_index))

    def Evaluate(self):
        if not numpy:
            print("Cannot evaluate without NumPy.")
            return

        self.MeasureColumns()

        dimensions = (len(self.rows), self.num_columns)

        m = numpy.zeros(dimensions)

        for row_index, row in enumerate(self.rows):
            for column_index, value in enumerate(row):
                is_float, float_value = value.AsFloat()
                if is_float:
                    m[row_index,column_index] = float_value

        for row_index, row in enumerate(self.rows):
            for column_index, value in enumerate(row):
                expression_match = CSVMatrix.EXPRESSION_RE.match(value.text)
                if expression_match:
                    self.EvaluateExpressionCell(m, row_index, column_index, value, expression_match)

class CsvSetOutputCommand(sublime_plugin.TextCommand):
    def run(self, edit, **args):
        if 'output' in args:
            self.view.replace(edit, sublime.Region(0, self.view.size()), args['output']);
        
        if 'saved_selection' in args:
            CSVMatrix.RestoreSelection(self.view, args['saved_selection'])

class CsvSortByColAscCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        self.matrix = CSVMatrix.FromView(self.view)
        if not self.matrix.valid:
            sublime.error_message(__name__ + ": The buffer doesn't appear to be a CSV file")
            return
        self.saved_selection = self.matrix.SaveSelection(self.view)

        self.view.window().show_quick_panel(['Use header row', 'Don\'t use header row'], self.on_select_header_done)

    def on_select_header_done(self, picked):
        if picked < 0:
            return
        use_header = picked == 0

        column_index = self.matrix.GetColumnIndexFromCursor(self.view)
        self.matrix.SortByColumn(column_index, SortDirection.Ascending, use_header)
        output = self.matrix.Format()

        self.view.run_command('csv_set_output', {'output': output, 'saved_selection': self.saved_selection})

class CsvSortByColDescCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        self.matrix = CSVMatrix.FromView(self.view)
        if not self.matrix.valid:
            sublime.error_message(__name__ + ": The buffer doesn't appear to be a CSV file")
            return
        self.saved_selection = self.matrix.SaveSelection(self.view)

        self.view.window().show_quick_panel(['Use header row', 'Don\'t use header row'], self.on_select_header_done)

    def on_select_header_done(self, picked):
        if picked < 0:
            return
        use_header = picked == 0

        column_index = self.matrix.GetColumnIndexFromCursor(self.view)
        self.matrix.SortByColumn(column_index, SortDirection.Descending, use_header)
        output = self.matrix.Format()

        self.view.run_command('csv_set_output', {'output': output, 'saved_selection': self.saved_selection})

class CsvInsertColCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        matrix = CSVMatrix.FromView(self.view)
        if not matrix.valid:
            sublime.error_message(__name__ + ": The buffer doesn't appear to be a CSV file")
            return
        saved_selection = matrix.SaveSelection(self.view)

        column_index = matrix.GetColumnIndexFromCursor(self.view)
        matrix.InsertColumn(column_index)

        output = matrix.Format()

        self.view.replace(edit, sublime.Region(0, self.view.size()), output);
        matrix.RestoreSelection(self.view, saved_selection)

class CsvDeleteColCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        matrix = CSVMatrix.FromView(self.view)
        if not matrix.valid:
            sublime.error_message(__name__ + ": The buffer doesn't appear to be a CSV file")
            return
        saved_selection = matrix.SaveSelection(self.view)

        column_index = matrix.GetColumnIndexFromCursor(self.view)
        matrix.DeleteColumn(column_index)

        output = matrix.Format()

        self.view.replace(edit, sublime.Region(0, self.view.size()), output);
        matrix.RestoreSelection(self.view, saved_selection)

class CsvDeleteTrailingColsCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        matrix = CSVMatrix.FromView(self.view)
        if not matrix.valid:
            sublime.error_message(__name__ + ": The buffer doesn't appear to be a CSV file")
            return
        saved_selection = matrix.SaveSelection(self.view)

        column_index = matrix.GetColumnIndexFromCursor(self.view)
        matrix.DeleteTrailingColumns(column_index)

        output = matrix.Format()

        self.view.replace(edit, sublime.Region(0, self.view.size()), output);
        matrix.RestoreSelection(self.view, saved_selection)

class CsvSelectColCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        matrix = CSVMatrix.FromView(self.view)
        if not matrix.valid:
            sublime.error_message(__name__ + ": The buffer doesn't appear to be a CSV file")
            return

        column_index = matrix.GetColumnIndexFromCursor(self.view)
        matrix.SelectColumn(column_index, self.view)

class CsvFormatCompactCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        matrix = CSVMatrix.FromView(self.view)
        if not matrix.valid:
            sublime.error_message(__name__ + ": The buffer doesn't appear to be a CSV file")
            return
        saved_selection = matrix.SaveSelection(self.view)

        output = matrix.FormatCompacted()

        self.view.replace(edit, sublime.Region(0, self.view.size()), output);
        matrix.RestoreSelection(self.view, saved_selection)

class CsvFormatExpandCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        matrix = CSVMatrix.FromView(self.view)
        if not matrix.valid:
            sublime.error_message(__name__ + ": The buffer doesn't appear to be a CSV file")
            return
        saved_selection = matrix.SaveSelection(self.view)

        output = matrix.FormatExpanded()

        self.view.replace(edit, sublime.Region(0, self.view.size()), output);
        matrix.RestoreSelection(self.view, saved_selection)

class CsvEvaluateCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        matrix = CSVMatrix.FromView(self.view)
        if not matrix.valid:
            sublime.error_message(__name__ + ": The buffer doesn't appear to be a CSV file")
            return
        saved_selection = matrix.SaveSelection(self.view)

        matrix.Evaluate()
        output = matrix.Format()

        self.view.replace(edit, sublime.Region(0, self.view.size()), output);
        matrix.RestoreSelection(self.view, saved_selection)
        
class CsvFormatCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        self.matrix = CSVMatrix.FromView(self.view)
        if not self.matrix.valid:
            sublime.error_message(__name__ + ": The buffer doesn't appear to be a CSV file")
            return

        self.view.window().show_input_panel('Format (ex. the {0} jumped over the {1})', "",
            self.on_done, self.on_change, self.on_cancel)

    CELL_RE = re.compile(r'{\d+}')

    def on_done(self, input):             
        output = ''
        numrows = len(self.matrix.rows)
        for rowindex, row in enumerate(self.matrix.rows):
            formatted_row = input
            for columnindex, column in enumerate(row):                
                formatted_row = formatted_row.replace('{' + str(columnindex) + '}', str(column.text))
            formatted_row = CsvFormatCommand.CELL_RE.sub('', formatted_row)
            output += formatted_row
            if rowindex < (numrows - 1):
                output += '\n'

        view = self.view.window().new_file()
        view.set_name('Formatted Output')
        view.set_scratch(True)

        view.run_command('csv_set_output', {'output': output});

    def on_change(self, input):
        pass

    def on_cancel(self):
        pass

class CsvSetDelimiterCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        self.view.window().show_input_panel('Delimiter character', "",
            self.on_done, self.on_change, self.on_cancel)

    def on_done(self, input):
        self.view.settings().set('delimiter', input)

    def on_change(self, input):
        pass

    def on_cancel(self):
        pass
