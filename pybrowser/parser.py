from __future__ import annotations
import ast, io, re, tokenize
from pathlib import Path
import libcst as cst
from libcst.metadata import MetadataWrapper, PositionProvider
from .model import Document, Kind, Member, Scope, Span
from .saving import file_signature

CATEGORY_RE=re.compile(r"^[ \t]*#[ \t]*category[ \t]*:[ \t]*(?P<name>[^\r\n#]+?)[ \t]*$",re.I)
class ParseError(ValueError):
    def __init__(self,message,line=None,column=None): super().__init__(message); self.line=line; self.column=column

def _starts(text):
    out=[0]; out.extend(m.end() for m in re.finditer("\n",text)); return out
def _end(text,starts,line): return starts[line] if line<len(starts) else len(text)
def _node_start(node,pos,positions):
    dec=getattr(node,"decorators",()); return positions[dec[0]].start.line if dec else pos.start.line
def _directive(text,start,lower):
    lines=text.splitlines(); i=start-1
    while i>=lower:
        value=lines[i-1]; match=CATEGORY_RE.match(value)
        if match:return match.group("name").strip(),i
        s=value.strip()
        if s and not s.startswith(("#","@")):break
        i-=1
    return None,None
def _span_start(text,start):
    _,line=_directive(text,start,1); return line or start
def _main(node): return cst.Module([]).code_for_node(node.test).replace(" ","") in {'__name__=="__main__"',"__name__=='__main__'"}
def _inferred(node,in_class):
    if isinstance(node,cst.SimpleStatementLine):
        if node.body and all(isinstance(x,(cst.Import,cst.ImportFrom)) for x in node.body):return "Imports"
        if len(node.body)==1 and isinstance(node.body[0],(cst.Assign,cst.AnnAssign,cst.AugAssign)):return "Variables"
    if isinstance(node,cst.FunctionDef):return "Uncategorized" if in_class else "Functions"
    if isinstance(node,cst.If) and _main(node):return "Runnable"
    return "Code"
def _assignment(node):
    target=node.targets[0].target if isinstance(node,cst.Assign) else node.target
    return cst.Module([]).code_for_node(target).strip()
def _member(text,node,scope,category,positions,starts,in_class):
    pos=positions[node]; first=_span_start(text,_node_start(node,pos,positions)); span=Span(starts[first-1],_end(text,starts,pos.end.line),first,pos.end.line)
    if isinstance(node,cst.SimpleStatementLine):
        if node.body and all(isinstance(x,(cst.Import,cst.ImportFrom)) for x in node.body): return Member(scope,category,text[span.start:span.end].splitlines()[0].strip(),Kind.IMPORTS,span)
        if len(node.body)==1 and isinstance(node.body[0],(cst.Assign,cst.AnnAssign,cst.AugAssign)): return Member(scope,category,_assignment(node.body[0]),Kind.ASSIGNMENT,span)
        return Member(scope,category,text[span.start:span.end].splitlines()[0].strip() or f"statement at line {first}",Kind.STATEMENT,span)
    if isinstance(node,cst.FunctionDef):
        params=cst.Module([]).code_for_node(node.params).strip(); prefix="async " if node.asynchronous else ""
        return Member(scope,category,f"{prefix}{node.name.value}{params}",Kind.METHOD if in_class else Kind.FUNCTION,span)
    if isinstance(node,cst.If) and _main(node): return Member(scope,category,'if __name__ == "__main__"',Kind.MAIN,span)
    return Member(scope,category,f"{type(node).__name__} at line {first}",Kind.BLOCK,span)
def _group(items,text):
    out=[]
    for item in items:
        if out and item.kind==out[-1].kind==Kind.IMPORTS and item.category==out[-1].category and not text[out[-1].span.end:item.span.start].strip():
            prev=out.pop(); span=Span(prev.span.start,item.span.end,prev.span.first,item.span.last); out.append(Member(item.scope,item.category,f"imports: lines {span.first}-{span.last}",Kind.IMPORTS,span))
        else:out.append(item)
    return out
def build_index(path:Path,text:str)->tuple[Scope,...]:
    try:module=cst.parse_module(text)
    except cst.ParserSyntaxError as e:raise ParseError(str(e),getattr(e,"raw_line",None),getattr(e,"raw_column",None)) from e
    wrapper=MetadataWrapper(module,unsafe_skip_copy=True); positions=wrapper.resolve(PositionProvider); starts=_starts(text); module_items=[]; scopes=[]
    for node in module.body:
        pos=positions[node]; found,_=_directive(text,_node_start(node,pos,positions),1); category=found or _inferred(node,False)
        if isinstance(node,cst.ClassDef):
            inside=[]
            if isinstance(node.body,cst.IndentedBlock):
                for child in node.body.body:
                    cp=positions[child]; found,_=_directive(text,_node_start(child,cp,positions),pos.start.line+1); cat=found or _inferred(child,True)
                    inside.append(_member(text,child,node.name.value,cat,positions,starts,True))
            scopes.append(Scope(node.name.value,tuple(_group(inside,text))))
        else:module_items.append(_member(text,node,"<module>",category,positions,starts,False))
    return (Scope("<module>",tuple(_group(module_items,text))),*scopes)
def read_document(path:Path)->Document:
    path=path.resolve(); raw=path.read_bytes(); encoding,_=tokenize.detect_encoding(io.BytesIO(raw).readline); text=raw.decode(encoding)
    return Document(path,text,encoding,"\r\n" if "\r\n" in text else "\n",text.endswith(("\n","\r")),file_signature(path),build_index(path,text))
def replacement(document:Document,member:Member,new:str)->str:
    old=document.source(member); new=new.replace("\r\n","\n").replace("\r","\n").rstrip("\n")
    if document.newline!="\n":new=new.replace("\n",document.newline)
    if old.endswith(("\n","\r")):new+=document.newline
    return document.text[:member.span.start]+new+document.text[member.span.end:]
def validate(text,filename):
    try:cst.parse_module(text); compile(text,filename,"exec",ast.PyCF_ONLY_AST)
    except cst.ParserSyntaxError as e:raise ParseError(str(e),getattr(e,"raw_line",None),getattr(e,"raw_column",None)) from e
    except SyntaxError as e:raise ParseError(e.msg,e.lineno,e.offset) from e
