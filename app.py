from flask import Flask, render_template, request, redirect, url_for, flash, Response, session
import os
import sqlite3
import csv
import io
import requests

URL_GOOGLE_SHEETS = "https://script.google.com/macros/s/AKfycbwGieoSUwVyiPvtnMiys_N7IreL8vHVtRMY_m0UDPm_gw5S8_OBmVXHcKR9Zxm9NUL0/exec"

app = Flask(__name__)
app.secret_key = 'cibiogen_secreto_clave'

UPLOAD_FOLDER = 'static/vouchers'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

DB_PATH = 'cibiogen.db'

CLAVE_SECRETA_MODERADOR = "kevin123"

def conectar_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# Crear tablas si no existen
with conectar_db() as conn:
    conn.execute('''
        CREATE TABLE IF NOT EXISTS pagos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tipo_pago INTEGER,
            ruta_voucher TEXT,
            estado TEXT DEFAULT 'pendiente'
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS inscritos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pago_id INTEGER,
            nombre TEXT,
            codigo TEXT,
            dni TEXT,
            FOREIGN KEY (pago_id) REFERENCES pagos(id)
        )
    ''')

# ---- RUTAS DE NAVEGACIÓN ----

@app.route('/')
def inicio():
    return render_template('index.html')

@app.route('/unaper')
def pagina_unaper():
    return render_template('unaper.html')

@app.route('/tenper')
def pagina_tenper():
    return render_template('tenper.html')

@app.route('/conper')
def pagina_conper():
    return render_template('conper.html', resultado=None, busqueda=False)


# ---- LÓGICA DE PROCESAMIENTO ----

# 1. Registro Individual
@app.route('/registrar_individual', methods=['POST'])
def registrar_individual():
    nombre = request.form.get('nombre')
    codigo = request.form.get('codigo')
    dni = request.form.get('dni')
    foto_voucher = request.files.get('voucher')

    if foto_voucher:
        nombre_archivo = f"voucher_ind_{codigo}_{foto_voucher.filename}"
        foto_voucher.save(os.path.join(app.config['UPLOAD_FOLDER'], nombre_archivo))

        with conectar_db() as conn:
            cursor = conn.execute(
                'INSERT INTO pagos (tipo_pago, ruta_voucher) VALUES (?, ?)', (1, nombre_archivo)
            )
            pago_id = cursor.lastrowid
            conn.execute(
                'INSERT INTO inscritos (pago_id, nombre, codigo, dni) VALUES (?, ?, ?, ?)',
                (pago_id, nombre, codigo, dni)
            )
            conn.commit()

        # --- ENVÍO A GOOGLE SHEETS (INDIVIDUAL) ---
        payload_individual = {
            "pago_id": pago_id,
            "nombre": nombre,
            "codigo": codigo,
            "dni": dni,
            "estado": "pendiente"
        }
        try:
            requests.post(URL_GOOGLE_SHEETS, json=payload_individual, timeout=5)
        except Exception as e:
            print(f"Error al enviar a Google Sheets: {e}")
        # ------------------------------------------

        flash('¡Inscripción recibida con éxito! El moderador revisará tu voucher.', 'exito')
        return redirect(url_for('inicio'))

    flash('Error: Falta el voucher.', 'error')
    return redirect(url_for('pagina_unaper'))


# 2. Registro Grupal
@app.route('/registrar_grupal', methods=['POST'])
def registrar_grupal():
    nombres = request.form.getlist('nombres[]')
    codigos = request.form.getlist('codigos[]')
    dnis = request.form.getlist('dnis[]')
    foto_voucher = request.files.get('voucher')

    if foto_voucher and nombres:
        nombre_archivo = f"voucher_group_{codigos[0]}_{foto_voucher.filename}"
        foto_voucher.save(os.path.join(app.config['UPLOAD_FOLDER'], nombre_archivo))

        with conectar_db() as conn:
            cursor = conn.execute(
                'INSERT INTO pagos (tipo_pago, ruta_voucher) VALUES (?, ?)', (2, nombre_archivo)
            )
            pago_id = cursor.lastrowid
            
            lista_integrantes = []
            for i in range(len(nombres)):
                if nombres[i].strip():
                    conn.execute(
                        'INSERT INTO inscritos (pago_id, nombre, codigo, dni) VALUES (?, ?, ?, ?)',
                        (pago_id, nombres[i], codigos[i], dnis[i])
                    )
                    # Almacenamos en lista para enviarlo en bloque a Google Sheets
                    lista_integrantes.append({
                        "nombre": nombres[i],
                        "codigo": codigos[i],
                        "dni": dnis[i]
                    })
            conn.commit()

        # --- ENVÍO A GOOGLE SHEETS (GRUPAL) ---
        payload_grupal = {
            "pago_id": pago_id,
            "estado": "pendiente",
            "integrantes": lista_integrantes
        }
        try:
            requests.post(URL_GOOGLE_SHEETS, json=payload_grupal, timeout=5)
        except Exception as e:
            print(f"Error al enviar a Google Sheets: {e}")
        # ----------------------------------------

        flash('¡Inscripción grupal recibida! El moderador verificará el voucher del grupo.', 'exito')
        return redirect(url_for('inicio'))

    flash('Error en los datos enviados.', 'error')
    return redirect(url_for('pagina_tenper'))


# 3. Consultar Estado
@app.route('/verificar_codigo', methods=['POST'])
def verificar_codigo():
    codigo_busqueda = request.form.get('codigo_busqueda')

    with conectar_db() as conn:
        resultado = conn.execute('''
            SELECT inscritos.nombre, pagos.estado
            FROM inscritos
            JOIN pagos ON inscritos.pago_id = pagos.id
            WHERE inscritos.codigo = ? OR inscritos.dni = ?
        ''', (codigo_busqueda, codigo_busqueda)).fetchone()

    return render_template('conper.html', resultado=resultado, busqueda=True)


# ---- CONTROL DE ACCESO / LOGIN SEGURIZADO ----

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        password_ingresada = request.form.get('password')
        if password_ingresada == CLAVE_SECRETA_MODERADOR:
            session['moderador_autenticado'] = True
            return redirect(url_for('panel_moderador'))
        else:
            return render_template('login.html', error="❌ Contraseña incorrecta. Intente de nuevo.")
    return render_template('login.html', error=None)

@app.route('/logout')
def logout():
    session.pop('moderador_autenticado', None)
    return redirect(url_for('inicio'))


# ---- PANEL MODERADOR ----

# 1. Ver panel (Protegido por Sesión)
@app.route('/moderador')
def panel_moderador():
    if not session.get('moderador_autenticado'):
        return "<h1>Acceso Denegado: Debe iniciar sesión primero.</h1><br><a href='/login'>Ir al Login</a>", 403

    with conectar_db() as conn:
        lista = conn.execute('''
            SELECT inscritos.nombre, inscritos.codigo, inscritos.dni,
                   pagos.id as pago_id, pagos.tipo_pago, pagos.ruta_voucher, pagos.estado
            FROM inscritos
            JOIN pagos ON inscritos.pago_id = pagos.id
            ORDER BY pagos.id DESC
        ''').fetchall()

    return render_template('moderador.html', lista=lista)


# 2. Aprobar / Rechazar pago
@app.route('/moderador/cambiar_estado', methods=['POST'])
def cambiar_estado():
    if not session.get('moderador_autenticado'):
        return "<h1>Acceso Denegado.</h1>", 403

    pago_id = request.form.get('pago_id')
    nuevo_estado = request.form.get('nuevo_estado')

    with conectar_db() as conn:
        conn.execute('UPDATE pagos SET estado = ? WHERE id = ?', (nuevo_estado, pago_id))
        conn.commit()

    return redirect(url_for('panel_moderador'))


# 3. Descargar CSV completo
@app.route('/moderador/descargar')
def descargar_excel():
    if not session.get('moderador_autenticado'):
        return "<h1>Acceso Denegado.</h1>", 403

    with conectar_db() as conn:
        lista = conn.execute('''
            SELECT inscritos.id, inscritos.nombre, inscritos.codigo, inscritos.dni,
                   pagos.id as pago_id, pagos.tipo_pago, pagos.ruta_voucher, pagos.estado
            FROM inscritos
            JOIN pagos ON inscritos.pago_id = pagos.id
            ORDER BY pagos.id ASC
        ''').fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID_INSCRITO', 'NOMBRE', 'CODIGO', 'DNI', 'ID_PAGO', 'TIPO_PAGO', 'VOUCHER', 'ESTADO'])
    for fila in lista:
        tipo = "Individual" if fila['tipo_pago'] == 1 else "Grupal"
        writer.writerow([
            fila['id'], fila['nombre'], fila['codigo'], fila['dni'],
            fila['pago_id'], tipo, fila['ruta_voucher'], fila['estado']
        ])

    output.seek(0)
    response = Response(output.getvalue(), mimetype='text/csv')
    response.headers.set("Content-Disposition", "attachment", filename="reporte_inscritos_cibiogen.csv")
    return response


if __name__ == '__main__':
    app.run(debug=True)
