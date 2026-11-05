from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction,QFont,QKeySequence,QTextCursor
from PySide6.QtWidgets import QFileDialog,QLabel,QListWidget,QMainWindow,QMessageBox,QSplitter,QStatusBar,QVBoxLayout,QWidget
from .parser import ParseError,read_document,replacement,validate
from .saving import atomic_write,changed
from .widgets.editor import Editor
class MainWindow(QMainWindow):
    def __init__(self,path=None):
        super().__init__();self.doc=None;self.scope=None;self.member=None;self.loading=False;self.resize(1400,900);self.setWindowTitle("PyBrowser");self._ui();self._actions()
        if path:self.open(path)
    def _ui(self):
        self.modules=QListWidget();self.scopes=QListWidget();self.categories=QListWidget();self.members=QListWidget();top=QSplitter(Qt.Orientation.Horizontal)
        for title,w in (("Modules",self.modules),("Scopes",self.scopes),("Categories",self.categories),("Members",self.members)):
            box=QWidget();lay=QVBoxLayout(box);lay.setContentsMargins(3,3,3,3);label=QLabel(title);label.setStyleSheet("font-weight:bold");lay.addWidget(label);lay.addWidget(w);top.addWidget(box)
        self.modules.currentRowChanged.connect(self._module);self.scopes.currentRowChanged.connect(self._scope);self.categories.currentTextChanged.connect(self._category);self.members.currentRowChanged.connect(self._member)
        self.crumb=QLabel("Open a Python file to begin");self.editor=Editor();font=QFont("0xProto Nerd Font",11);font.setStyleHint(QFont.StyleHint.Monospace);self.editor.setFont(font);self.editor.textChanged.connect(self._modified)
        lower=QWidget();lay=QVBoxLayout(lower);lay.addWidget(self.crumb);lay.addWidget(self.editor);main=QSplitter(Qt.Orientation.Vertical);main.addWidget(top);main.addWidget(lower);main.setSizes([280,620]);self.setCentralWidget(main);self.setStatusBar(QStatusBar())
    def _actions(self):
        op=QAction("Open Python File...",self);op.setShortcut(QKeySequence.StandardKey.Open);op.triggered.connect(self.choose);save=QAction("Save Member",self);save.setShortcut(QKeySequence.StandardKey.Save);save.triggered.connect(self.save);menu=self.menuBar().addMenu("&File");menu.addActions([op,save]);self.addActions([op,save])
    def _modified(self):
        if not self.loading:self.setWindowModified(self.editor.document().isModified())
    def _confirm_discard(self):
        if not self.editor.document().isModified():return True
        answer=QMessageBox.question(self,"Unsaved member edit","Save the current member before navigating?",QMessageBox.StandardButton.Save|QMessageBox.StandardButton.Discard|QMessageBox.StandardButton.Cancel,QMessageBox.StandardButton.Save)
        if answer==QMessageBox.StandardButton.Save:self.save();return not self.editor.document().isModified()
        return answer==QMessageBox.StandardButton.Discard
    def choose(self):
        name,_=QFileDialog.getOpenFileName(self,"Open Python File","","Python files (*.py)")
        if name and self._confirm_discard():self.open(Path(name))
    def open(self,path,restore=None):
        try:self.doc=read_document(path)
        except Exception as e:QMessageBox.critical(self,"Cannot open file",str(e));return
        self.loading=True;self.modules.clear();self.modules.addItem(self.doc.path.name);self.modules.setCurrentRow(0);self.loading=False;self.setWindowTitle(self.doc.path.name+"[*] - PyBrowser")
        if restore:self._restore(*restore)
    def _module(self,row):
        if row<0 or not self.doc:return
        self.scopes.blockSignals(True);self.scopes.clear();self.scopes.addItems([x.name for x in self.doc.scopes]);self.scopes.blockSignals(False);self.scopes.setCurrentRow(0)
    def _scope(self,row):
        if row<0 or not self.doc:return
        if self.member and not self.loading and not self._confirm_discard():self.scopes.setCurrentRow(next((i for i,x in enumerate(self.doc.scopes) if x.name==self.member.scope),0));return
        self.scope=self.doc.scopes[row];self.categories.clear();self.categories.addItems(sorted(dict.fromkeys(x.category for x in self.scope.members),key=lambda x:(x=="Uncategorized",x.casefold())))
        if self.categories.count():self.categories.setCurrentRow(0)
    def _category(self,category):
        if self.member and not self.loading and self.editor.document().isModified() and not self._confirm_discard():return
        self.members.clear()
        if self.scope:
            for member in (x for x in self.scope.members if x.category == category):
                self.members.addItem(member.label)
                self.members.item(self.members.count() - 1).setToolTip(member.tooltip or member.label)
        if self.members.count():self.members.setCurrentRow(0)
    def _visible(self):
        cat=self.categories.currentItem().text() if self.categories.currentItem() else "";return [x for x in self.scope.members if x.category==cat] if self.scope else []
    def _member(self,row):
        items=self._visible();new=items[row] if 0<=row<len(items) else None
        if self.member and new!=self.member and not self.loading and self.editor.document().isModified() and not self._confirm_discard():return
        self.member=new;self.loading=True
        if new:self.editor.setPlainText(self.doc.source(new));self.editor.document().setModified(False);self.crumb.setText(f"{self.doc.path.name} > {new.scope} > {new.category} > {new.label}")
        else:self.editor.clear()
        self.loading=False;self.setWindowModified(False)
    def save(self):
        if not self.doc or not self.member:return
        if changed(self.doc) and QMessageBox.question(self,"File changed","The file changed outside PyBrowser. Overwrite it?",QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
        location=(self.member.scope,self.member.category,self.member.label);candidate=replacement(self.doc,self.member,self.editor.toPlainText())
        try:validate(candidate,str(self.doc.path));atomic_write(self.doc,candidate);self.open(self.doc.path,location);self.editor.document().setModified(False);self.setWindowModified(False);self.statusBar().showMessage("Saved",5000)
        except ParseError as e:
            QMessageBox.critical(self,"Syntax error",f"{e}\n\nLine: {e.line or '?'}  Column: {e.column or '?'}")
            if e.line:self._highlight_error(e.line,e.column or 1)
        except Exception as e:QMessageBox.critical(self,"Save failed",str(e))
    def _highlight_error(self,line,column):
        cursor=self.editor.textCursor();cursor.movePosition(QTextCursor.MoveOperation.Start);cursor.movePosition(QTextCursor.MoveOperation.Down,QTextCursor.MoveMode.MoveAnchor,max(0,line-1));cursor.movePosition(QTextCursor.MoveOperation.Right,QTextCursor.MoveMode.MoveAnchor,max(0,column-1));cursor.select(QTextCursor.SelectionType.LineUnderCursor);self.editor.setTextCursor(cursor);self.editor.setFocus()
    def _restore(self,scope,category,label):
        for i,item in enumerate(self.doc.scopes):
            if item.name==scope:self.scopes.setCurrentRow(i);break
        found=self.categories.findItems(category,Qt.MatchFlag.MatchExactly)
        if found:self.categories.setCurrentItem(found[0])
        found=self.members.findItems(label,Qt.MatchFlag.MatchExactly)
        if found:self.members.setCurrentItem(found[0])
        elif self.members.count():self.members.setCurrentRow(0)
    def closeEvent(self,event):event.accept() if self._confirm_discard() else event.ignore()
