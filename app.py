from flask import Flask, render_template, request, redirect, url_for, flash, Response
import os
import sqlite3
import csv
import io

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
            for i in range(len(nombres)):
                if nombres[i].strip():
                    conn.execute(
                        'INSERT INTO inscritos (pago_id, nombre, codigo, dni) VALUES (?, ?, ?, ?)',
                        (pago_id, nombres[i], codigos[i], dnis[i])
                    )
            conn.commit()

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


# ---- PANEL MODERADOR ----

# 1. Ver panel
@app.route('/moderador')
def panel_moderador():
    clave = request.args.get('clave')
    if clave != CLAVE_SECRETA_MODERADOR:
        return "<h1>Acceso Denegado: Contraseña incorrecta o ausente.</h1>", 403

    with conectar_db() as conn:
        lista = conn.execute('''
            SELECT inscritos.nombre, inscritos.codigo, inscritos.dni,
                   pagos.id as pago_id, pagos.tipo_pago, pagos.ruta_voucher, pagos.estado
            FROM inscritos
            JOIN pagos ON inscritos.pago_id = pagos.id
            ORDER BY pagos.id DESC
        ''').fetchall()

    return render_template('moderador.html', lista=lista, clave=CLAVE_SECRETA_MODERADOR)


# 2. Aprobar / Rechazar pago
@app.route('/moderador/cambiar_estado', methods=['POST'])
def cambiar_estado():
    clave = request.form.get('clave')
    if clave != CLAVE_SECRETA_MODERADOR:
        return "<h1>Acceso Denegado.</h1>", 403

    pago_id = request.form.get('pago_id')
    nuevo_estado = request.form.get('nuevo_estado')

    with conectar_db() as conn:
        conn.execute('UPDATE pagos SET estado = ? WHERE id = ?', (nuevo_estado, pago_id))
        conn.commit()

    return redirect(f'/moderador?clave={CLAVE_SECRETA_MODERADOR}')


# 3. Descargar CSV completo
@app.route('/moderador/descargar')
def descargar_excel():
    clave = request.args.get('clave')
    if clave != CLAVE_SECRETA_MODERADOR:
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