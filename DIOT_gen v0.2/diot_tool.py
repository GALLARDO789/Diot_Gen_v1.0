#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import csv, json, unicodedata, os, re
from datetime import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

DEBUG = True  # pon False cuando ya jale

# ---------- util ----------
def normalize_name(s: str) -> str:
    if not s: return ""
    s = s.lower()
    s = unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode("ascii")
    rep = [" s.a.", " sa ", " s.a", " de ", " c.v", " c. v",
           " s. de r.l", " s de rl", " s de r l", " s. de r. l."]
    for r in rep: s = s.replace(r, " ")
    for ch in ",.-_/&()": s = s.replace(ch, " ")
    return re.sub(r"\s+", " ", s).strip()

RFC_RE = re.compile(r"^[A-Z&Ñ]{3,4}\d{6}[A-Z0-9]{2,3}$", re.IGNORECASE)

def split_proveedor(raw: str):
    if not raw: return "", "", ""
    s = " ".join(str(raw).split())
    parts = s.split()
    rfc_guess = ""
    nombre = s
    if parts and RFC_RE.match(parts[0]):
        rfc_guess = parts[0].upper()
        nombre = " ".join(parts[1:]) if len(parts) > 1 else ""
    nombre = re.split(r"\b(F-?|FOLIO|FACT(URA)?|#)\b", nombre, maxsplit=1, flags=re.IGNORECASE)[0]
    nombre = nombre.strip() or rfc_guess
    key = rfc_guess or normalize_name(nombre)
    return rfc_guess, nombre, key

def to_num(x):
    if x is None: return 0.0
    if isinstance(x, (int, float)): return float(x)
    s = str(x).strip().replace("$", "").replace(",", "")
    if s.startswith("(") and s.endswith(")"): s = "-" + s[1:-1]
    try: return float(s)
    except: return 0.0

def ym(s):
    if not s: return ""
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y", "%m/%d/%Y"):
        try:
            d = datetime.strptime(s, fmt)
            return f"{d.year:04d}-{d.month:02d}"
        except: pass
    return s[:7] if len(s) >= 7 else ""

def completar_iva(base16, iva16, total, subtotal=None, iva_suelto=None):
    base16 = to_num(base16); iva16 = to_num(iva16)
    total = to_num(total); subtotal = to_num(subtotal); iva_suelto = to_num(iva_suelto)

    if base16 or iva16:
        if not iva16 and base16: iva16 = round(base16 * 0.16, 2)
        if not base16 and iva16: base16 = round(iva16 / 0.16, 2)
        return round(base16, 2), round(iva16, 2)

    if subtotal and iva_suelto: return round(subtotal, 2), round(iva_suelto, 2)
    if iva_suelto and not subtotal: return round(iva_suelto/0.16, 2), round(iva_suelto, 2)

    if total:
        b = total / 1.16
        return round(b, 2), round(total - b, 2)

    return 0.0, 0.0

# ---------- catálogo ----------
def load_catalog(path):
    try:
        if not os.path.isfile(path) or os.path.getsize(path) == 0: return []
        with open(path, "r", encoding="utf-8") as f: data = json.load(f)
        out = []
        for p in data:
            out.append({
                "rfc": (p.get("rfc","") or "").upper(),
                "nombre_legal": p.get("nombre_legal") or "",
                "aliases": list({normalize_name(a) for a in (p.get("aliases") or []) if a}),
                "tipoTercero": p.get("tipoTercero") or "04",
                "tipoOperacion": p.get("tipoOperacion") or "85",
            })
        return out
    except: return []

def save_catalog(path, catalog):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=2)

def find_in_catalog(catalog, nombre, rfc):
    rfc = (rfc or "").upper().strip()
    if rfc:
        hit = next((p for p in catalog if p["rfc"] == rfc), None)
        if hit: return hit
    norm = normalize_name(nombre)
    return next((p for p in catalog if norm in p["aliases"]), None)

def upsert_catalog_fields(catalog, rfc, nombre_original=None, alias_to_add=None,
                          tipoTercero=None, tipoOperacion=None):
    rfc = (rfc or "").upper().strip()
    hit = next((p for p in catalog if p["rfc"] == rfc), None)
    if hit:
        a = normalize_name(alias_to_add or "")
        if a and a not in hit["aliases"]: hit["aliases"].append(a)
        if nombre_original and not hit.get("nombre_legal"): hit["nombre_legal"] = nombre_original
        if tipoTercero: hit["tipoTercero"] = tipoTercero
        if tipoOperacion: hit["tipoOperacion"] = tipoOperacion
        return
    catalog.append({
        "rfc": rfc,
        "nombre_legal": (nombre_original or "").strip(),
        "aliases": [normalize_name(alias_to_add or nombre_original or "")] if (alias_to_add or nombre_original) else [],
        "tipoTercero": tipoTercero or "04",
        "tipoOperacion": tipoOperacion or "85",
    })

# ---------- mapeo encabezados ----------
def build_header_map(headers):
    hlow = [h.strip().lower() for h in headers]
    def pick(*names):
        names = [n.lower() for n in names]
        for i, h in enumerate(hlow):
            if h in names: return headers[i]
        return None
    return {
        "FechaCFDI": pick("fechacfdi","fecha","fechafactura","fecha factura"),
        "FechaPago": pick("fechapago","fecha pago"),
        "Proveedor": pick("proveedor","nombre","nombreproveedor","beneficiario","concepto"),
        "RFC":       pick("rfc","rfc proveedor","rfcproveedor"),
        "Metodo":    pick("metodopago","metodo","forma de pago","forma_pago"),
        "Tipo":      pick("tipo","movimiento","naturaleza"),
        "Estatus":   pick("estatus","status","estado"),
        "Debe":      pick("debe"),
        "Haber":     pick("haber"),
        "Total":     pick("total","importe","monto","total facturado","total comprobante"),
        "SubTotal":  pick("subtotal","sub total","base","gravado","importe neto"),
        "IVA":       pick("iva","impuesto","impuestos trasladados","iva 16","iva16%"),
        "Base16":    pick("base16","base16%","base 16","gravado 16","tasa 16","base 16%"),
        "IVA16":     pick("iva16","iva 16","iva 16%"),
        "Base0":     pick("base0","base 0","tasa0","tasa 0","0%"),
        "Exento":    pick("baseexento","exento","exento iva","no gravado"),
    }

def looks_egreso(tipo_val):
    t = (tipo_val or "").strip().upper()
    return t in ("E","EGRESO","EGRESOS","PAGO","PAGOS","CXP","PROVEEDOR","PROVEEDORES","DR")

def is_cancelled(estatus):
    s = (estatus or "").strip().lower()
    return s in ("cancelado","cancelada","canc","cnl","anulado","anulada")

# ---------- procesamiento ----------
def process_csv(csv_path, catalog, periodo, debe_mode="total", progress_callback=None):
    """
    debe_mode: "total" -> Debe es total con IVA; "iva" -> Debe es solo IVA
    """
    accum = {}
    pendientes = {}
    egresos_contados = 0

    with open(csv_path, "r", encoding="utf-8", errors="replace", newline="") as f:
        sample = f.read(4096); f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
            delim = dialect.delimiter
        except:
            delim = ";" if sample.count(";") > sample.count(",") else ","

        reader = csv.reader(f, delimiter=delim)

        # encabezado
        raw_rows, header_row = [], None
        for _ in range(50):
            try: r = next(reader)
            except StopIteration: break
            raw_rows.append(r)
            low = [c.strip().lower() for c in r]
            if any(k in low for k in ("concepto","proveedor","nombre","nombreproveedor")) and \
               any(k in low for k in ("debe","total","subtotal","iva","haber","base16","base 16")):
                header_row = r; break
        if header_row is None:
            header_row = next((r for r in raw_rows if any(c.strip() for c in r)), [])
        headers = [h.strip() for h in header_row]
        if not headers: raise RuntimeError("No se encontró encabezado en el CSV.")

        H = build_header_map(headers)
        if not H["Proveedor"]: raise RuntimeError("No se encontró la columna Proveedor/Nombre en el CSV.")
        idx = {h:i for i,h in enumerate(headers)}

        if DEBUG:
            msg = [f"Delimitador: '{delim}'",
                   f"Headers ({len(headers)}): {headers}",
                   "Mapeo:", *[f"  {k}: {H[k]}" for k in H],
                   f"Periodo: {periodo}", f"Modo Debe: {debe_mode}"]
            messagebox.showinfo("DEBUG", "\n".join(msg))

        total_leidas = 0
        incluidas = 0

        for i, row in enumerate(reader, start=1):
            if not row or not any(str(x).strip() for x in row): continue
            total_leidas += 1
            if progress_callback and i % 2500 == 0: progress_callback(i)

            def g(key):
                col = H.get(key)
                if not col: return ""
                j = idx.get(col)
                if j is None or j >= len(row): return ""
                return row[j]

            tipo_val = g("Tipo")
            deb = to_num(g("Debe")); hab = to_num(g("Haber"))
            es_egreso_tipo = looks_egreso(tipo_val) if H.get("Tipo") else False
            es_egreso_mov  = (deb > 0 and hab == 0)
            if not (es_egreso_tipo or es_egreso_mov): continue
            if is_cancelled(g("Estatus")): continue

            metodo = (g("Metodo") or "").strip().upper()
            fecha  = g("FechaPago") if metodo == "PPD" else g("FechaCFDI")
            ym_fecha = ym(fecha)
            pasa_mes = True if ((H.get("FechaCFDI") is None and H.get("FechaPago") is None) or not ym_fecha) else (ym_fecha == periodo)
            if not pasa_mes: continue

            proveedor_raw = (g("Proveedor") or "").strip()
            rfc_col = (g("RFC") or "").strip().upper()
            rfc_guess, nombre_guess, key_group = split_proveedor(proveedor_raw)
            rfc_orig = rfc_col or rfc_guess
            nombre_prov = nombre_guess or proveedor_raw

            base0    = to_num(g("Base0"))
            exento   = to_num(g("Exento"))
            base16   = to_num(g("Base16"))
            iva16    = to_num(g("IVA16"))
            total    = to_num(g("Total"))
            subtotal = to_num(g("SubTotal"))
            iva_sue  = to_num(g("IVA"))

            # --- modo Debe ---
            if total == 0 and subtotal == 0 and deb > 0:
                if debe_mode == "total":
                    total = deb
                else:  # "iva"
                    iva_sue = deb

            base16, iva16 = completar_iva(base16, iva16, total, subtotal, iva_sue)

            provCat = find_in_catalog(catalog, nombre_prov, rfc_orig)
            if provCat:
                rfc_final = provCat["rfc"]
                nombre_final = provCat["nombre_legal"] or nombre_prov
                tipoTercero = provCat["tipoTercero"] or "04"
                tipoOperacion = provCat["tipoOperacion"] or "85"
            else:
                if key_group:
                    item = pendientes.get(key_group, {"nombre": nombre_prov, "monto": 0.0})
                    item["monto"] += (total if total else (base16 + iva16))
                    pendientes[key_group] = item
                rfc_final = "SINRFC"
                nombre_final = nombre_prov
                tipoTercero = "04"
                tipoOperacion = "85"

            a = accum.get(rfc_final)
            if not a:
                a = {"RFC": rfc_final, "Nombre": nombre_final,
                     "Base16": 0.0, "IVA16": 0.0, "Base0": 0.0, "Exento": 0.0,
                     "TipoTercero": tipoTercero, "TipoOperacion": tipoOperacion}
                accum[rfc_final] = a
            a["Base16"] += base16; a["IVA16"] += iva16
            a["Base0"]  += base0;  a["Exento"] += exento

            egresos_contados += 1
            incluidas += 1

        if DEBUG:
            messagebox.showinfo("DEBUG",
                                f"Filas leídas: {total_leidas}\n"
                                f"Incluidas (mes/criterios): {incluidas}\n"
                                f"En acumulador (incluye SINRFC): {len(accum)}")

    out_rows, sB16, sIVA, sB0, sEX = [], 0.0, 0.0, 0.0, 0.0
    for k, v in accum.items():
        if k == "SINRFC": continue
        r = {"RFC": v["RFC"], "Nombre": v["Nombre"],
             "Base16": round(v["Base16"], 2), "IVA16": round(v["IVA16"], 2),
             "Base0": round(v["Base0"], 2), "BaseExento": round(v["Exento"], 2),
             "TipoTercero": v["TipoTercero"], "TipoOperacion": v["TipoOperacion"]}
        sB16 += r["Base16"]; sIVA += r["IVA16"]; sB0 += r["Base0"]; sEX += r["BaseExento"]
        out_rows.append(r)

    out_rows.sort(key=lambda r: r["RFC"])
    totals = {"Base16": sB16, "IVA16": sIVA, "Base0": sB0, "Exento": sEX, "Egresos": egresos_contados}
    return out_rows, pendientes, totals

# ---------- export ----------
def export_diot_csv(path, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["RFC","Nombre","Base16","IVA16","Base0","BaseExento","TipoTercero","TipoOperacion"])
        for r in rows:
            w.writerow([r["RFC"], r["Nombre"],
                        f'{r["Base16"]:.2f}', f'{r["IVA16"]:.2f}',
                        f'{r["Base0"]:.2f}', f'{r["BaseExento"]:.2f}',
                        r["TipoTercero"], r["TipoOperacion"]])

def export_pendientes_csv(path, pendientes):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ProveedorDetectado","TotalPeriodo","RFC"])
        for _, item in sorted(pendientes.items(), key=lambda kv: kv[1]["nombre"]):
            w.writerow([item["nombre"], f'{item["monto"]:.2f}', ""])

# ---------- UI ----------
TERCEROS=[("04","04 - Proveedor nacional"),("05","05 - Proveedor extranjero"),("15","15 - Globales*")]
OPERACIONES=[("85","85 - Otros"),("03","03 - Prestacion de servicios"),("06","06 - Uso o goce temporal de bienes")]

class DIOTApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("DIOT – Procesador CSV + Catálogo (debug)")
        self.geometry("1150x680"); self.minsize(1000, 620)

        self.csv_path = tk.StringVar()
        self.json_path = tk.StringVar()
        self.periodo = tk.StringVar(value=datetime.now().strftime("%Y-%m"))
        self.debe_mode = tk.StringVar(value="total")  # modo de interpretación del Debe

        self.catalog, self.result_rows = [], []
        self.pendientes, self.totals = {}, {}
        self._build_ui()

    def _build_ui(self):
        frmTop = ttk.Frame(self, padding=10); frmTop.pack(fill="x")

        ttk.Label(frmTop, text="CSV (COI):").grid(row=0, column=0, sticky="w")
        ttk.Entry(frmTop, textvariable=self.csv_path, width=60).grid(row=0, column=1, padx=5, sticky="we")
        ttk.Button(frmTop, text="Buscar…", command=self.pick_csv).grid(row=0, column=2, padx=(4,10))

        ttk.Label(frmTop, text="Catálogo JSON:").grid(row=1, column=0, sticky="w", pady=(6,0))
        ttk.Entry(frmTop, textvariable=self.json_path, width=60).grid(row=1, column=1, padx=5, sticky="we", pady=(6,0))
        ttk.Button(frmTop, text="Buscar…", command=self.pick_json).grid(row=1, column=2, padx=(4,10), pady=(6,0))

        ttk.Label(frmTop, text="Mes (AAAA-MM):").grid(row=0, column=3, padx=(10,5))
        ttk.Entry(frmTop, textvariable=self.periodo, width=10).grid(row=0, column=4)

        # Selector de modo Debe
        box = ttk.LabelFrame(frmTop, text="Interpretación de 'Debe'")
        box.grid(row=1, column=3, columnspan=2, padx=(10,0), sticky="w")
        ttk.Radiobutton(box, text="Total con IVA (estándar)", variable=self.debe_mode, value="total").grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(box, text="Solo IVA", variable=self.debe_mode, value="iva").grid(row=1, column=0, sticky="w")

        ttk.Button(frmTop, text="Procesar", command=self.run_process).grid(row=0, column=5, rowspan=2, padx=(12,0))

        frmMid = ttk.Frame(self, padding=(10,0,10,10)); frmMid.pack(fill="both", expand=True)

        left = ttk.Frame(frmMid); left.pack(side="left", fill="both", expand=True)
        ttk.Label(left, text="DIOT agrupado por RFC").pack(anchor="w")

        cols = ("RFC","Nombre","Base16","IVA16","Base0","Exento","TipoTercero","TipoOperacion")
        self.tree = ttk.Treeview(left, columns=cols, show="headings", height=16)
        for c, w in zip(cols, (140,280,90,90,90,90,110,120)):
            self.tree.heading(c, text=c)
            self.tree.column(c, width=w, anchor="e" if c in ("Base16","IVA16","Base0","Exento") else "w")
        self.tree.pack(fill="both", expand=True, pady=(4,4))
        self.tree.bind("<<TreeviewSelect>>", self.on_select_row)

        self.lblTotals = ttk.Label(left, text="Totales: Base16 0.00 | IVA16 0.00 | Base0 0.00 | Exento 0.00")
        self.lblTotals.pack(anchor="w", pady=(0,6))

        frmBtns = ttk.Frame(left); frmBtns.pack(anchor="w", pady=(0,8))
        ttk.Button(frmBtns, text="Exportar DIOT.csv", command=self.save_diot, state="disabled").pack(side="left", padx=(0,6))
        # guardo referencia y empiezo disabled, la activamos tras procesar
        self.btn_save_catalog = ttk.Button(frmBtns, text="Guardar catálogo actualizado",
                                           command=self.save_catalog_json, state="disabled")
        self.btn_save_catalog.pack(side="left", padx=(0,6))
        ttk.Button(frmBtns, text="Exportar pendientes.csv", command=self.save_pendientes, state="disabled").pack(side="left")

        right = ttk.Frame(frmMid, width=360); right.pack(side="left", fill="y", padx=(10,0))

        ed = ttk.LabelFrame(right, text="Editar proveedor seleccionado"); ed.pack(fill="x", pady=(0,8))
        self.ed_rfc = tk.StringVar(); self.ed_nombre = tk.StringVar()
        self.ed_tipoT = tk.StringVar(value="04"); self.ed_tipoO = tk.StringVar(value="85")

        frmEd1 = ttk.Frame(ed, padding=6); frmEd1.pack(fill="x")
        ttk.Label(frmEd1, text="RFC:").grid(row=0, column=0, sticky="w")
        ttk.Entry(frmEd1, textvariable=self.ed_rfc, state="readonly").grid(row=0, column=1, sticky="we", padx=4)
        ttk.Label(frmEd1, text="Nombre:").grid(row=1, column=0, sticky="w")
        ttk.Entry(frmEd1, textvariable=self.ed_nombre, state="readonly").grid(row=1, column=1, sticky="we", padx=4)

        frmEd2 = ttk.Frame(ed, padding=6); frmEd2.pack(fill="x")
        ttk.Label(frmEd2, text="TipoTercero:").grid(row=0, column=0, sticky="w")
        self.cmbT = ttk.Combobox(frmEd2, textvariable=self.ed_tipoT, values=[x for x,_ in TERCEROS], state="normal", width=6)
        self.cmbT.grid(row=0, column=1, sticky="w"); ttk.Label(frmEd2, text="(04 Nac | 05 Ext)").grid(row=0, column=2, padx=4)
        ttk.Label(frmEd2, text="TipoOperacion:").grid(row=1, column=0, sticky="w", pady=(4,0))
        self.cmbO = ttk.Combobox(frmEd2, textvariable=self.ed_tipoO, values=[x for x,_ in OPERACIONES], state="normal", width=6)
        self.cmbO.grid(row=1, column=1, sticky="w", pady=(4,0))
        ttk.Label(frmEd2, text="(85 otros, 03 serv, 06 goce)").grid(row=1, column=2, padx=4, pady=(4,0))

        frmEdBtns = ttk.Frame(ed, padding=6); frmEdBtns.pack(fill="x")
        self.btn_save_types = ttk.Button(frmEdBtns, text="Guardar tipos en catálogo",
                                         command=self.save_types_to_catalog, state="disabled")
        self.btn_save_types.pack(side="left")
        ttk.Button(frmEdBtns, text="Reprocesar", command=self.run_process).pack(side="left", padx=6)

        pend = ttk.LabelFrame(right, text="Pendientes (capturar RFC)"); pend.pack(fill="both", expand=True)
        self.treePend = ttk.Treeview(pend, columns=("Proveedor","Total"), show="headings", height=10)
        self.treePend.heading("Proveedor", text="Proveedor detectado")
        self.treePend.heading("Total", text="Total de cargos y abonos del período")
        self.treePend.column("Proveedor", width=220, anchor="w")
        self.treePend.column("Total", width=120, anchor="e")
        self.treePend.pack(fill="both", expand=True, pady=(4,4))

        frmP = ttk.Frame(pend); frmP.pack(anchor="w", pady=(0,6))
        self.btn_add_rfc = ttk.Button(frmP, text="Agregar RFC…", command=self.add_rfc_to_selected, state="disabled")
        self.btn_add_rfc.pack(side="left", padx=(0,6))
        # NUEVO: botón Eliminar pendiente
        self.btn_delete_pend = ttk.Button(frmP, text="Eliminar", command=self.delete_selected_pending, state="disabled")
        self.btn_delete_pend.pack(side="left", padx=(0,6))
        ttk.Button(frmP, text="Reprocesar", command=self.run_process).pack(side="left")

        # Habilitar/Deshabilitar según selección en pendientes
        self.treePend.bind("<<TreeviewSelect>>", self.on_select_pending)

        self.status = ttk.Label(self, text="Listo.", anchor="w"); self.status.pack(fill="x")

    def pick_csv(self):
        p = filedialog.askopenfilename(title="Selecciona CSV del COI", filetypes=[("CSV","*.csv"),("Todos","*.*")])
        if p: self.csv_path.set(p)

    def pick_json(self):
        p = filedialog.askopenfilename(title="Selecciona catálogo JSON", filetypes=[("JSON","*.json"),("Todos","*.*")])
        if p:
            self.json_path.set(p); self.catalog = load_catalog(p)
            msg = f"Cargado catálogo con {len(self.catalog)} proveedores." if self.catalog else "Archivo vacío o inválido. Continuarás con catálogo vacío."
            messagebox.showinfo("Catálogo", msg)

    def set_status(self, t): self.status.config(text=t); self.update_idletasks()

    def run_process(self):
        csvp = self.csv_path.get().strip()
        jsonp = self.json_path.get().strip()
        periodo = self.periodo.get().strip()
        if not os.path.isfile(csvp): messagebox.showerror("CSV","Selecciona un CSV válido."); return
        if jsonp and not self.catalog: self.catalog = load_catalog(jsonp)

        self.set_status("Procesando CSV…")
        self.tree.delete(*self.tree.get_children()); self.treePend.delete(*self.treePend.get_children())

        try:
            rows, pendientes, totals = process_csv(
                csvp, self.catalog, periodo, debe_mode=self.debe_mode.get(),
                progress_callback=lambda i: self.set_status(f"Procesando filas… {i:,}")
            )
        except Exception as e:
            messagebox.showerror("Procesar", str(e)); self.set_status("Error."); return

        self.result_rows, self.pendientes, self.totals = rows, pendientes, totals

        for r in rows:
            self.tree.insert("", "end", values=(r["RFC"], r["Nombre"],
                f'{r["Base16"]:.2f}', f'{r["IVA16"]:.2f}', f'{r["Base0"]:.2f}',
                f'{r["BaseExento"]:.2f}', r["TipoTercero"], r["TipoOperacion"]))

        for _, item in sorted(pendientes.items(), key=lambda kv: kv[1]["nombre"]):
            self.treePend.insert("", "end", values=(item["nombre"], f'{item["monto"]:.2f}'))

        self.lblTotals.config(text=(f"Totales: Base16 {totals['Base16']:.2f} | IVA16 {totals['IVA16']:.2f} | "
                                    f"Base0 {totals['Base0']:.2f} | Exento {totals['Exento']:.2f}  "
                                    f"(Egresos incluidos: {totals['Egresos']:,})"))

        # habilitaciones
        has_rows = bool(rows)
        if has_rows:
            self.btn_save_types.config(state="normal")
        self.btn_save_catalog.config(state="normal")
        self.btn_add_rfc.config(state=("normal" if pendientes else "disabled"))
        # el botón eliminar arranca deshabilitado hasta seleccionar
        self.btn_delete_pend.config(state="disabled")

        self.set_status(f"Listo. RFC en DIOT: {len(rows)} | Pendientes: {len(pendientes)}")

    def on_select_row(self, _evt):
        sel = self.tree.selection()
        if not sel: return
        rfc, nombre, *_rest, tipoT, tipoO = self.tree.item(sel[0], "values")
        self.ed_rfc.set(rfc); self.ed_nombre.set(nombre); self.ed_tipoT.set(tipoT); self.ed_tipoO.set(tipoO)
        self.btn_save_types.config(state="normal")

    def on_select_pending(self, _evt):
        """Habilita acciones cuando hay un pendiente seleccionado."""
        sel = self.treePend.selection()
        has_sel = bool(sel)
        self.btn_add_rfc.config(state=("normal" if has_sel else "disabled"))
        self.btn_delete_pend.config(state=("normal" if has_sel else "disabled"))

    def _remove_pending_by_nombre(self, nombre: str):
        """Quita un pendiente por nombre del diccionario interno."""
        key_to_delete = None
        for k, v in self.pendientes.items():
            if v.get("nombre") == nombre:
                key_to_delete = k
                break
        if key_to_delete is not None:
            self.pendientes.pop(key_to_delete, None)

    def delete_selected_pending(self):
        """Elimina el pendiente seleccionado (solo de la lista y memoria local)."""
        sel = self.treePend.selection()
        if not sel:
            messagebox.showinfo("Pendientes", "Selecciona un proveedor para eliminar.")
            return
        nombre = self.treePend.item(sel[0], "values")[0]
        if not messagebox.askyesno("Eliminar pendiente",
                                   f"¿Eliminar '{nombre}' de la lista de pendientes?\n"
                                   "Nota: esto NO afecta el CSV original ni el catálogo."):
            return
        # quita de UI y de estructura interna
        self.treePend.delete(sel[0])
        self._remove_pending_by_nombre(nombre)

        # si ya no quedan pendientes, deshabilita botones
        if not self.treePend.get_children():
            self.btn_add_rfc.config(state="disabled")
            self.btn_delete_pend.config(state="disabled")

    def save_types_to_catalog(self):
        rfc=self.ed_rfc.get().strip(); nombre=self.ed_nombre.get().strip()
        if not rfc: return
        upsert_catalog_fields(self.catalog, rfc, nombre_original=nombre, alias_to_add=nombre,
                              tipoTercero=self.ed_tipoT.get().strip(), tipoOperacion=self.ed_tipoO.get().strip())
        self.btn_save_catalog.config(state="normal")
        messagebox.showinfo("Catálogo", f"Tipos guardados para {rfc}. (Recuerda guardar el catálogo y/o reprocesar)")

    def save_diot(self):
        out = filedialog.asksaveasfilename(defaultextension=".csv",
                                           initialfile=f"DIOT_{self.periodo.get().strip()}.csv",
                                           filetypes=[("CSV","*.csv")])
        if not out: return
        export_diot_csv(out, self.result_rows); messagebox.showinfo("Exportar DIOT", f"Guardado: {out}")

    def save_pendientes(self):
        out = filedialog.asksaveasfilename(defaultextension=".csv",
                                           initialfile="pendientes.csv",
                                           filetypes=[("CSV","*.csv")])
        if not out: return
        export_pendientes_csv(out, self.pendientes); messagebox.showinfo("Pendientes", f"Guardado: {out}")

    def save_catalog_json(self):
        """Guardar el catálogo en el JSON actual o pedir ruta si no hay."""
        path = self.json_path.get().strip()
        if not path:
            path = filedialog.asksaveasfilename(defaultextension=".json",
                                                initialfile="catalogo_actualizado.json",
                                                filetypes=[("JSON","*.json")])
        if not path: return
        try:
            save_catalog(path, self.catalog)
            self.json_path.set(path)
            messagebox.showinfo("Catálogo", f"Guardado: {path}")
        except Exception as e:
            messagebox.showerror("Catálogo", f"No se pudo guardar:\n{e}")

    def add_rfc_to_selected(self):
        """Agregar RFC para un proveedor pendiente y actualizar catálogo."""
        sel = self.treePend.selection()
        if not sel:
            messagebox.showinfo("Pendientes", "Selecciona un proveedor en la lista de pendientes.")
            return
        nombre = self.treePend.item(sel[0], "values")[0]
        rfc = simpledialog.askstring("Agregar RFC", f"RFC para:\n\n{nombre}\n\n(12/13 + homoclave)")
        if not rfc: return
        rfc = rfc.strip().upper()
        if not (12 <= len(rfc) <= 16):
            if not messagebox.askyesno("RFC", "Formato de RFC no luce válido. ¿Agregar de todos modos?"):
                return

        # subir a catálogo
        upsert_catalog_fields(self.catalog, rfc, nombre_original=nombre, alias_to_add=nombre)
        self.btn_save_catalog.config(state="normal")

        # quitar de pendientes UI
        self.treePend.delete(sel[0])

        # también de la estructura interna
        self._remove_pending_by_nombre(nombre)

        messagebox.showinfo("Pendientes", "RFC agregado. Reprocesa para que se agrupe en DIOT.")

if __name__ == "__main__":
    DIOTApp().mainloop()
