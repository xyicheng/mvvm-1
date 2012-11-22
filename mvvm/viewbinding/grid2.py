import wx
import wx.grid
import traits.api as traits

from mvvm.viewbinding import display
from mvvm.viewbinding.interactive import ChoiceBinding, ComboBinding


class GridBinding(object):
    """Binds a Grid to a Table

    Example code for saving a grid when closing the window:

        window.Bind(wx.EVT_CLOSE, close)

        def close(evt):
            if grid.IsCellEditControlEnabled():
                grid.DisableCellEditControl()
                wx.CallAfter(window.Close)
                return evt.Veto()
            if not table.SaveGrid():
                return evt.Veto()
            evt.Skip()
    """
    def __init__(self, field, trait, mapping, types=None, commit_on='row'):
        self.field = field
        self.trait = trait
        self.commit_on = commit_on
        self.mapping = [Column.init(col) for col in mapping]
        self.types = types or {}

        self.table = getattr(trait[0], trait[1]+"_table")
        self.table.mapping = self.mapping
        self.table.commit_on = commit_on
        self.table.grid = self.field
        self.field.SetTable(self.table)
        self.on_table_message()

        self.field.Bind(wx.grid.EVT_GRID_CELL_CHANGED, self.on_cell_changed)
        self.field.Bind(wx.grid.EVT_GRID_SELECT_CELL, self.on_select_cell)
        self.field.Bind(wx.EVT_KEY_DOWN, self.on_key_down)

        for type_k, type_v in types.items():
            self.field.RegisterDataType(type_k, type_v.renderer, type_v.editor)

        # Inject our table message listener
        process_table_message = self.field.ProcessTableMessage
        self.field.ProcessTableMessage = lambda message:\
            process_table_message(message) and self.on_table_message(message)

        self.veto_next_select_cell = False

    def on_table_message(self, message=None):
        # Only apply styles to the rows / cols
        for col_idx in range(self.table.GetNumberCols()):
            col = self.mapping[col_idx]
            if col.width is not None:
                self.field.SetColSize(col_idx, col.width)

    def on_cell_changed(self, evt):
        if self.commit_on == 'cell':
            if not self.table.SaveCell(evt.Row, evt.Col):
                # Veto do_select_cell as that would in turn trigger
                # on_select_cell and re-run the savecell, and resulting in
                # the same error message.
                self.veto_next_select_cell = True
        # The grid does not always render the grid correctly when a dialog  was
        # shown, so it needs a `Refresh` for the active cell to be highlighted.
        self.field.Refresh()

    def do_select_cell(self, row, col):
        # See `on_cell_changed` on why this method can be `Veto`ed.
        if not self.veto_next_select_cell:
            self.field.SetGridCursor(row, col)
        self.veto_next_select_cell = False
        # The grid does not always render the grid correctly when a dialog  was
        # shown, so it needs a `Refresh` for the active cell to be highlighted.
        self.field.Refresh()

    def on_select_cell(self, evt):
        if self.commit_on == 'grid':
            return evt.Skip()

        from_ = (self.field.GetGridCursorRow(), self.field.GetGridCursorCol())
        to_ = (evt.Row, evt.Col)

        if self.field.IsCellEditControlEnabled():
            # @todo By inspecting the current value of the control, we can
            # check if the value is to be accepted; thus .Veto() before the
            # celleditor is actually disabled.
            self.field.DisableCellEditControl()
            wx.CallAfter(self.do_select_cell, *to_)
            return evt.Veto()

        elif self.commit_on == 'cell' and from_ != to_:
            # Try to save the cell, even though it will fail as on_cell_changed
            # will only handle the happy flow. Failing to save will show the
            # previous error message (again) and remembers the user of the
            # faulty input.
            if not self.table.SaveCell(*from_):
                return evt.Veto()

        elif self.commit_on == 'row' and from_[0] != to_[0]:
            if not self.table.SaveRow(from_[0]):
                return evt.Veto()

        elif self.commit_on == 'col' and from_[1] != to_[1]:
            if not self.table.SaveCol(from_[1]):
                return evt.Veto()

        evt.Skip()

    def on_key_down(self, event):
        if event.GetKeyCode() in (wx.WXK_DELETE, wx.WXK_BACK, wx.WXK_NUMPAD_DELETE):
            if self.field.GetSelectedRows():
                self.table.DeleteRows(self.field.GetSelectedRows())
                self.field.ClearSelection()
            else:
                # Remove the value of the current field if delete/backspace
                # was pressed when in viewing mode.
                self.table.SetValue(self.field.GridCursorRow,
                                    self.field.GridCursorCol, None)
                # Might need to save changes when commit_on = cell
                self.on_cell_changed(wx.grid.GridEvent(
                    self.field.GetId(), wx.grid.wxEVT_GRID_CELL_CHANGED,
                    self.field, self.field.GridCursorRow,
                    self.field.GridCursorCol))
            return
        elif event.GetKeyCode() in [wx.WXK_NUMPAD_ENTER, wx.WXK_RETURN]:
            # Need to stop cell editing first, saving the cell value before
            # trying to commit.
            #  * Normal: move cursor, commit, save cell
            #  * Desired: move cursor, save cell, commit
            self.field.DisableCellEditControl()

            # Create a new row after the current row. On success, move the
            # cursor to the left-most cell of the new row.
            if self.field.GridCursorRow == self.table.GetNumberRows() - 1:
                self.table.CreateRow()
            self.field.SetGridCursor(self.field.GridCursorRow + 1, 0)
            self.field.MakeCellVisible(self.field.GridCursorRow, 0)

            # Move to the left-most cell of the next row.
            return

        event.Skip()


class Column(display.Column):
    def __init__(self, attribute, label, width=None, type_name=None):
        self.attribute = attribute
        self.label = label
        self.width = width
        self.type_name = type_name


class ChoiceType(object):
    class Trait(traits.HasTraits):
        value = traits.Any

    class Editor(wx.grid.PyGridCellEditor):
        def __init__(self, choices=None, provider=None):
            super(ChoiceType.Editor, self).__init__()
            self.trait = ChoiceType.Trait()
            self.choices = choices
            self.provider = provider

        def Create(self, parent, id, evtHandler):
            if self.provider:
                self.SetControl(wx.ComboBox(parent, id))
                self.binding = ComboBinding(self.GetControl(),
                                            self.trait, 'value',
                                            self.provider)
            else:
                self.SetControl(wx.Choice(parent, id))
                self.binding = ChoiceBinding(self.GetControl(),
                                             self.trait, 'value',
                                             self.choices)
            self.GetControl().PushEventHandler(evtHandler)

        def SetSize(self, rect):
            # Adjust for minimal height of the control
            height = self.GetControl().GetBestSize()[1]
            rect.y = rect.y + rect.height / 2 - max(rect.height, height) / 2
            rect.height = max(rect.height, height)
            super(ChoiceType.Editor, self).SetSize(rect)

        def BeginEdit(self, row, col, grid):
            value = grid.GetCellValue(row, col)
            self.GetControl().SetValue(value)
            self.GetControl().SetFocus()
            self.GetControl().Popup()

        def Reset(self):
            # @todo use wx_patch [ESC] to reset value to original text
            raise NotImplementedError()

        def EndEdit(self, row, col, grid, prev):
            grid.GetTable().SetValue(row, col,
                                     self.GetControl().GetClientData(self.GetControl().Selection))

    def __init__(self, choices=None, provider=None):
        self.trait = self.Trait()
        self.choices = choices
        self.provider = provider

        self.editor = self.Editor(choices=choices, provider=provider)
        self.renderer = wx.grid.GridCellStringRenderer()
