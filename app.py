import os, sqlite3
from datetime import date
from functools import wraps
from flask import Flask, g, render_template, request, redirect, url_for, session, flash, abort
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "cambia-esta-clave")
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "inventario.db")

PIEZAS = [
 ("P001","Rodamiento 6205","Rodamientos",40,10,"A-01"),("P002","Rodamiento 6001","Rodamientos",3,10,"A-02"),
 ("P003","Sensor inductivo M12","Sensores",15,5,"B-01"),("P004","Fusible 10 A","Eléctrico",50,20,"B-02"),
 ("P005","Contactor 24 V","Eléctrico",12,4,"B-03"),("P006","Motor DC 24 V","Motores",4,10,"C-01"),
 ("P007","Motor trifásico 1 HP","Motores",6,2,"C-02"),("P008","Sensor óptico","Sensores",2,5,"B-04"),
 ("P009","Banda dentada B-52","Transmisión",9,4,"D-01"),("P010","Cadena de rodillos #40","Transmisión",14,5,"D-02"),
 ("P011","Banda industrial","Transmisión",0,5,"D-03"),("P012","Válvula solenoide 1/2\"","Neumática",8,3,"E-01"),
 ("P013","Cilindro neumático 50 mm","Neumática",5,2,"E-02"),("P014","Manguera hidráulica 3/8\"","Hidráulica",30,10,"F-01"),
 ("P015","Bomba hidráulica","Hidráulica",3,2,"F-02"),("P016","Filtro de aceite","Lubricación",25,8,"G-01"),
 ("P017","Grasa industrial 1 kg","Lubricación",18,6,"G-02"),("P018","Relevador 24 VDC","Eléctrico",2,6,"B-05"),
 ("P019","Tornillo M8 (caja 100)","Fijación",22,5,"H-01"),("P020","Sello mecánico 35 mm","Sellos",0,3,"H-02"),
 ("P021","Acoplamiento flexible","Transmisión",7,3,"D-04"),("P022","Termopar tipo K","Sensores",11,4,"B-06")]

def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close(_):
    d = g.pop("db", None)
    if d: d.close()

def init_db():
    c = sqlite3.connect(DB)
    c.executescript("""
    CREATE TABLE IF NOT EXISTS usuarios(id INTEGER PRIMARY KEY, usuario TEXT UNIQUE, nombre TEXT, clave TEXT, rol TEXT);
    CREATE TABLE IF NOT EXISTS piezas(codigo TEXT PRIMARY KEY, nombre TEXT, categoria TEXT, cantidad INTEGER, minimo INTEGER, ubicacion TEXT);
    CREATE TABLE IF NOT EXISTS solicitudes(id INTEGER PRIMARY KEY, usuario_id INTEGER, codigo TEXT, cantidad INTEGER, estado TEXT, fecha TEXT);
    CREATE TABLE IF NOT EXISTS movimientos(id INTEGER PRIMARY KEY, fecha TEXT, tipo TEXT, codigo TEXT, cantidad INTEGER, usuario TEXT, nota TEXT);
    """)
    if not c.execute("SELECT 1 FROM usuarios").fetchone():
        for u, n, p, r in [("admin","Administrador","admin123","admin"),("gerente","Gerente","gerente123","gerente"),("tecnico","Técnico 1","tecnico123","tecnico")]:
            c.execute("INSERT INTO usuarios(usuario,nombre,clave,rol) VALUES(?,?,?,?)", (u, n, generate_password_hash(p), r))
        c.executemany("INSERT INTO piezas VALUES(?,?,?,?,?,?)", PIEZAS)
        for p in PIEZAS:
            c.execute("INSERT INTO movimientos(fecha,tipo,codigo,cantidad,usuario,nota) VALUES(?,?,?,?,?,?)", (str(date.today()),"Entrada",p[0],p[3],"admin","Inventario inicial"))
    c.commit(); c.close()

def estado(p):
    if p["cantidad"] == 0: return ("Sin stock", "no")
    if p["cantidad"] <= p["minimo"]: return ("Stock bajo", "lo")
    return ("En stock", "ok")
app.jinja_env.globals["estado"] = estado

def acceso(*roles):
    def deco(f):
        @wraps(f)
        def w(*a, **k):
            if "uid" not in session: return redirect(url_for("login"))
            if roles and session["rol"] not in roles: abort(403)
            return f(*a, **k)
        return w
    return deco

def mov(tipo, codigo, cant, usuario, nota):
    db().execute("INSERT INTO movimientos(fecha,tipo,codigo,cantidad,usuario,nota) VALUES(?,?,?,?,?,?)", (str(date.today()), tipo, codigo, cant, usuario, nota))

def entero(v):
    try: return int(v)
    except (TypeError, ValueError): return -1

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = db().execute("SELECT * FROM usuarios WHERE usuario=?", (request.form["usuario"].strip(),)).fetchone()
        if u and check_password_hash(u["clave"], request.form["clave"]):
            session.clear(); session.update(uid=u["id"], usuario=u["usuario"], nombre=u["nombre"], rol=u["rol"])
            return redirect(url_for("dashboard"))
        flash("Usuario o contraseña incorrectos.", "no")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear(); return redirect(url_for("login"))

@app.route("/")
@acceso()
def dashboard():
    ps = db().execute("SELECT * FROM piezas").fetchall()
    n = {"total": len(ps), "ok": 0, "lo": 0, "no": 0}
    for p in ps: n[estado(p)[1]] += 1
    alertas = db().execute("SELECT * FROM piezas WHERE cantidad<=minimo ORDER BY cantidad").fetchall()
    pend = db().execute("SELECT COUNT(*) FROM solicitudes WHERE estado='Pendiente'").fetchone()[0]
    return render_template("dashboard.html", n=n, alertas=alertas, pend=pend)

@app.route("/piezas")
@acceso()
def piezas():
    q, cat = request.args.get("q", "").strip(), request.args.get("cat", "")
    sql, par = "SELECT * FROM piezas WHERE (codigo LIKE ? OR nombre LIKE ? OR ubicacion LIKE ?)", [f"%{q}%"] * 3
    if cat: sql += " AND categoria=?"; par.append(cat)
    cats = [r[0] for r in db().execute("SELECT DISTINCT categoria FROM piezas ORDER BY 1")]
    return render_template("piezas.html", ps=db().execute(sql + " ORDER BY codigo", par).fetchall(), cats=cats, q=q, cat=cat)

@app.route("/piezas/nueva", methods=["GET", "POST"])
@app.route("/piezas/<codigo>/editar", methods=["GET", "POST"])
@acceso("admin")
def pieza_form(codigo=None):
    p = db().execute("SELECT * FROM piezas WHERE codigo=?", (codigo,)).fetchone() if codigo else None
    if codigo and not p: abort(404)
    if request.method == "POST":
        f = request.form
        d = (f["nombre"].strip(), f["categoria"].strip(), entero(f["cantidad"]), entero(f["minimo"]), f["ubicacion"].strip())
        if not all(d[:2]) or not d[4] or d[2] < 0 or d[3] < 0:
            flash("Completa todos los campos con valores válidos.", "no")
        elif p:
            if d[2] != p["cantidad"]:
                dif = d[2] - p["cantidad"]; mov("Entrada" if dif > 0 else "Salida", codigo, abs(dif), session["usuario"], "Ajuste manual")
            db().execute("UPDATE piezas SET nombre=?,categoria=?,cantidad=?,minimo=?,ubicacion=? WHERE codigo=?", d + (codigo,))
            db().commit(); flash("Pieza actualizada.", "ok"); return redirect(url_for("piezas"))
        else:
            cod = f["codigo"].strip().upper()
            if not cod or db().execute("SELECT 1 FROM piezas WHERE codigo=?", (cod,)).fetchone():
                flash("El código está vacío o ya existe.", "no")
            else:
                db().execute("INSERT INTO piezas VALUES(?,?,?,?,?,?)", (cod,) + d)
                if d[2]: mov("Entrada", cod, d[2], session["usuario"], "Alta de pieza")
                db().commit(); flash("Pieza registrada.", "ok"); return redirect(url_for("piezas"))
    return render_template("pieza_form.html", p=p or request.form)

@app.post("/piezas/<codigo>/eliminar")
@acceso("admin")
def pieza_eliminar(codigo):
    db().execute("DELETE FROM piezas WHERE codigo=?", (codigo,)); db().commit()
    flash("Pieza eliminada.", "ok"); return redirect(url_for("piezas"))

@app.post("/piezas/<codigo>/entrada")
@acceso("admin")
def pieza_entrada(codigo):
    n = entero(request.form.get("cantidad"))
    if n <= 0: flash("Escribe una cantidad mayor a 0.", "no")
    else:
        db().execute("UPDATE piezas SET cantidad=cantidad+? WHERE codigo=?", (n, codigo))
        mov("Entrada", codigo, n, session["usuario"], "Recepción de inventario"); db().commit(); flash("Entrada registrada.", "ok")
    return redirect(url_for("piezas"))

@app.route("/solicitudes")
@acceso("gerente", "tecnico")
def solicitudes():
    sql = "SELECT s.*, u.usuario AS solicitante, p.nombre, p.cantidad AS disp FROM solicitudes s JOIN usuarios u ON u.id=s.usuario_id LEFT JOIN piezas p ON p.codigo=s.codigo"
    par = ()
    if session["rol"] == "tecnico": sql += " WHERE s.usuario_id=?"; par = (session["uid"],)
    rows = db().execute(sql + " ORDER BY s.id DESC", par).fetchall()
    ps = db().execute("SELECT codigo,nombre,cantidad FROM piezas ORDER BY codigo").fetchall()
    return render_template("solicitudes.html", rows=rows, ps=ps, sel=request.args.get("pieza", ""))

@app.post("/solicitudes/nueva")
@acceso("tecnico")
def solicitud_nueva():
    n = entero(request.form.get("cantidad"))
    if n <= 0 or not db().execute("SELECT 1 FROM piezas WHERE codigo=?", (request.form.get("codigo"),)).fetchone():
        flash("Elige una pieza y una cantidad mayor a 0.", "no")
    else:
        db().execute("INSERT INTO solicitudes(usuario_id,codigo,cantidad,estado,fecha) VALUES(?,?,?,?,?)", (session["uid"], request.form["codigo"], n, "Pendiente", str(date.today())))
        db().commit(); flash("Solicitud enviada.", "ok")
    return redirect(url_for("solicitudes"))

@app.post("/solicitudes/<int:sid>/resolver")
@acceso("gerente")
def solicitud_resolver(sid):
    s = db().execute("SELECT s.*, u.usuario FROM solicitudes s JOIN usuarios u ON u.id=s.usuario_id WHERE s.id=? AND s.estado='Pendiente'", (sid,)).fetchone()
    if not s: abort(404)
    if request.form["accion"] == "aprobar":
        p = db().execute("SELECT * FROM piezas WHERE codigo=?", (s["codigo"],)).fetchone()
        if not p or p["cantidad"] < s["cantidad"]:
            flash("No hay existencias suficientes para aprobar.", "no"); return redirect(url_for("solicitudes"))
        db().execute("UPDATE piezas SET cantidad=cantidad-? WHERE codigo=?", (s["cantidad"], s["codigo"]))
        db().execute("UPDATE solicitudes SET estado='Aprobada' WHERE id=?", (sid,))
        mov("Salida", s["codigo"], s["cantidad"], s["usuario"], f"SOL-{sid} aprobada por {session['usuario']}")
        flash("Solicitud aprobada; existencias actualizadas.", "ok")
    else:
        db().execute("UPDATE solicitudes SET estado='Rechazada' WHERE id=?", (sid,)); flash("Solicitud rechazada.", "ok")
    db().commit(); return redirect(url_for("solicitudes"))

@app.route("/movimientos")
@acceso("admin", "gerente")
def movimientos():
    return render_template("movimientos.html", rows=db().execute("SELECT * FROM movimientos ORDER BY id DESC").fetchall())

@app.route("/usuarios", methods=["GET", "POST"])
@acceso("admin")
def usuarios():
    if request.method == "POST":
        f = request.form
        if not f["usuario"].strip() or not f["nombre"].strip() or len(f["clave"]) < 4 or f["rol"] not in ("admin", "gerente", "tecnico"):
            flash("Completa todo; la contraseña requiere 4 caracteres o más.", "no")
        else:
            try:
                db().execute("INSERT INTO usuarios(usuario,nombre,clave,rol) VALUES(?,?,?,?)", (f["usuario"].strip(), f["nombre"].strip(), generate_password_hash(f["clave"]), f["rol"]))
                db().commit(); flash("Usuario creado.", "ok")
            except sqlite3.IntegrityError:
                flash("Ese usuario ya existe.", "no")
    return render_template("usuarios.html", us=db().execute("SELECT * FROM usuarios ORDER BY id").fetchall())

@app.post("/usuarios/<int:uid>/eliminar")
@acceso("admin")
def usuario_eliminar(uid):
    if uid == session["uid"]: flash("No puedes eliminar tu propia cuenta.", "no")
    else: db().execute("DELETE FROM usuarios WHERE id=?", (uid,)); db().commit(); flash("Usuario eliminado.", "ok")
    return redirect(url_for("usuarios"))

@app.route("/reportes")
@acceso("gerente")
def reportes():
    d = db()
    cats = d.execute("SELECT categoria, COUNT(*) n, SUM(cantidad) u, SUM(cantidad<=minimo) a FROM piezas GROUP BY categoria").fetchall()
    top = d.execute("SELECT m.codigo, p.nombre, SUM(m.cantidad) t FROM movimientos m LEFT JOIN piezas p ON p.codigo=m.codigo WHERE m.tipo='Salida' GROUP BY m.codigo ORDER BY t DESC LIMIT 5").fetchall()
    tot = {t: d.execute("SELECT COALESCE(SUM(cantidad),0) FROM movimientos WHERE tipo=?", (t,)).fetchone()[0] for t in ("Entrada", "Salida")}
    return render_template("reportes.html", cats=cats, top=top, tot=tot)

if __name__ == "__main__":
    init_db(); app.run(debug=True)
