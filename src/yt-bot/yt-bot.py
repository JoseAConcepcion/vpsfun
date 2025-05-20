import os
import logging
import subprocess
import requests
import asyncio
from telegram import Update, InputFile, ChatAction
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    CallbackContext,
    ContextTypes
)

# Configuración
TOKEN = os.getenv("YT_TELEGRAM_BOT") 
AUTHORIZED_USERS = [int(id_str.strip()) for id_str in os.getenv("MY_TELEGRAM_ID", "").split(",") if id_str.strip()]
MAX_FILE_SIZE = 2 * 1024 * 1024 * 1024  # 2GB (límite de Telegram)
PART_SIZE = 1.9 * 1024 * 1024 * 1024  # 1.9GB (para dejar margen)
TEMP_DIR = "temp_downloads"
CHUNK_SIZE = 1024 * 1024  # 1MB para chunks de subida
UPLOAD_TIMEOUT = 300  # 5 minutos para subidas

# Configurar logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def ensure_temp_dir():
    """Asegura que el directorio temporal existe."""
    if not os.path.exists(TEMP_DIR):
        os.makedirs(TEMP_DIR)

def is_authorized(user_id):
    """Verifica si el usuario está autorizado."""
    return user_id in AUTHORIZED_USERS

def start(update: Update, context: CallbackContext) -> None:
    """Mensaje de inicio."""
    if not is_authorized(update.effective_user.id):
        update.message.reply_text('No autorizado.')
        return
    
    update.message.reply_text(
        '👋 Hola! Soy un bot para descargar y subir archivos grandes.\n\n'
        'Comandos disponibles:\n'
        '/download <url> - Descargar video de YouTube\n'
        '/upload <file_path> - Subir archivo\n'
        '/list [path] - Listar archivos\n'
        '/clean - Limpiar archivos temporales\n'
        '/status - Ver estado del servidor'
    )

async def download_video(update: Update, context: CallbackContext) -> None:
    """Descarga un video de YouTube usando yt-dlp."""
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text('No autorizado.')
        return
    
    if not context.args:
        await update.message.reply_text('Por favor proporciona una URL. Ejemplo: /download https://youtu.be/ejemplo')
        return
    
    url = ' '.join(context.args)
    ensure_temp_dir()
    
    try:
        await update.message.reply_text(f'⏬ Descargando video de {url}...')
        
        # Configuración base de yt-dlp
        cmd = [
            'yt-dlp',
            '-o', f'{TEMP_DIR}/%(title)s.%(ext)s',
            '--merge-output-format', 'mkv',
            '--no-playlist',
            '--limit-rate', '50M',
            '--socket-timeout', '30',
            '--retries', '10',
            '--fragment-retries', '10',
            '--extractor-retries', '5',
            url
        ]
        
        # Añadir cookies si existen
        cookies_path = os.path.join(TEMP_DIR, 'cookies.txt')
        if os.path.exists(cookies_path):
            cmd[1:1] = [  # Insertar después del comando principal
                '--cookies', cookies_path,
                '--force-ipv4',
                '--mark-watched'
            ]
            logger.info("Usando cookies para la descarga")
        else:
            await update.message.reply_text('⚠️ Descargando sin cookies - Algunos videos pueden requerir autenticación')
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            raise Exception(f'Error en yt-dlp: {stderr.decode()}')
        
        # Encontrar el archivo descargado
        downloaded_files = [f for f in os.listdir(TEMP_DIR) if f.endswith('.mp4')]
        if not downloaded_files:
            raise Exception('No se pudo encontrar el archivo descargado.')
        
        filename = max(
            [os.path.join(TEMP_DIR, f) for f in downloaded_files],
            key=os.path.getctime
        )
        
        await update.message.reply_text(
            f'✅ Descarga completada: {os.path.basename(filename)}\n'
            f'📏 Tamaño: {os.path.getsize(filename)/1024/1024:.2f} MB\n'
            f'Usa /upload {filename} para subirlo.'
        )
        
    except Exception as e:
        await update.message.reply_text(f'❌ Error al descargar: {str(e)}')
        logger.error(f"Error al descargar {url}: {e}")

def split_large_file(file_path):
    """Divide un archivo grande en partes usando 7zip."""
    try:
        file_dir = os.path.dirname(file_path)
        file_name = os.path.basename(file_path)
        archive_name = os.path.splitext(file_name)[0]
        output_path = os.path.join(file_dir, archive_name)
        
        cmd = [
            '7z',
            'a',
            '-v{}'.format(int(PART_SIZE)),
            '-mx0',  # Sin compresión (más rápido)
            f'{output_path}.7z',
            file_path
        ]
        
        subprocess.run(cmd, check=True)
        
        # Obtener las partes creadas
        parts = sorted([f for f in os.listdir(file_dir) 
                      if f.startswith(archive_name) and f.endswith('.7z.001')])
        
        return [os.path.join(file_dir, p) for p in parts]
    
    except Exception as e:
        logger.error(f"Error al dividir {file_path}: {e}")
        raise


def list_files(update: Update, context: CallbackContext) -> None:
    """Lista los archivos disponibles."""
    if not is_authorized(update.effective_user.id):
        update.message.reply_text('No autorizado.')
        return
    
    path = '.' if not context.args else ' '.join(context.args)
    
    if not os.path.exists(path):
        update.message.reply_text('❌ La ruta no existe.')
        return
    
    try:
        files = []
        total_size = 0
        count = 0
        
        for entry in os.scandir(path):
            if entry.is_file():
                size_mb = entry.stat().st_size / 1024 / 1024
                total_size += size_mb
                count += 1
                files.append(f"{entry.name} ({size_mb:.2f} MB)")
        
        if not files:
            update.message.reply_text('No hay archivos en este directorio.')
        else:
            message = (
                f"📂 Contenido de {path}:\n"
                f"📊 Total archivos: {count}\n"
                f"📦 Tamaño total: {total_size:.2f} MB\n\n"
                "Archivos:\n" + '\n'.join(files[:20]
                )  # Limitar a 20 archivos
            )
            
            if len(files) > 20:
                message += f"\n\n...y {len(files)-20} archivos más."
            
            update.message.reply_text(message)
    
    except Exception as e:
        update.message.reply_text(f'❌ Error al listar archivos: {str(e)}')

def clean_temp(update: Update, context: CallbackContext) -> None:
    """Limpia los archivos temporales."""
    if not is_authorized(update.effective_user.id):
        update.message.reply_text('No autorizado.')
        return
    
    try:
        ensure_temp_dir()
        deleted = 0
        total_freed = 0
        
        for filename in os.listdir(TEMP_DIR):
            file_path = os.path.join(TEMP_DIR, filename)
            try:
                file_size = os.path.getsize(file_path) / 1024 / 1024
                os.remove(file_path)
                deleted += 1
                total_freed += file_size
            except Exception as e:
                logger.error(f"Error al eliminar {file_path}: {e}")
        
        update.message.reply_text(
            f'🧹 Eliminados {deleted} archivos temporales.\n'
            f'💾 Espacio liberado: {total_freed:.2f} MB'
        )
    except Exception as e:
        update.message.reply_text(f'❌ Error al limpiar: {str(e)}')

def server_status(update: Update, context: CallbackContext) -> None:
    """Muestra el estado del servidor."""
    if not is_authorized(update.effective_user.id):
        update.message.reply_text('No autorizado.')
        return
    
    try:
        # Obtener uso de disco
        disk = os.statvfs('/')
        disk_total = (disk.f_blocks * disk.f_frsize) / 1024 / 1024 / 1024
        disk_used = ((disk.f_blocks - disk.f_bfree) * disk.f_frsize) / 1024 / 1024 / 1024
        disk_percent = (disk_used / disk_total) * 100
        
        # Obtener uso de memoria
        with open('/proc/meminfo', 'r') as mem:
            mem_lines = mem.readlines()
            mem_total = int(mem_lines[0].split()[1]) / 1024
            mem_free = int(mem_lines[1].split()[1]) / 1024
            mem_used = mem_total - mem_free
            mem_percent = (mem_used / mem_total) * 100
        
        # Obtener carga del sistema
        load = os.getloadavg()
        
        message = (
            "🖥️ Estado del servidor:\n\n"
            f"💽 Disco: {disk_used:.2f}/{disk_total:.2f} GB ({disk_percent:.1f}% usado)\n"
            f"🧠 Memoria: {mem_used:.2f}/{mem_total:.2f} GB ({mem_percent:.1f}% usado)\n"
            f"📊 Carga del sistema: {load[0]:.2f}, {load[1]:.2f}, {load[2]:.2f}\n"
            f"📂 Espacio temporal: {len(os.listdir(TEMP_DIR))} archivos"
        )
        
        update.message.reply_text(message)
    
    except Exception as e:
        update.message.reply_text(f'❌ Error al obtener estado: {str(e)}')
        
async def handle_cookies(update: Update, context: CallbackContext) -> None:
    """Maneja la subida y validación de cookies."""
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text('⚠️ No autorizado.')
        return
    
    if not update.message.document:
        await update.message.reply_text('ℹ️ Envía el archivo cookies.txt como documento.')
        return
    
    doc = update.message.document
    cookies_path = os.path.join(TEMP_DIR, 'cookies.txt')
    
    try:
        # Validaciones del archivo
        if not doc.file_name.lower().endswith('.txt'):
            await update.message.reply_text('❌ El archivo debe ser .txt')
            return
            
        if doc.file_size > 10 * 1024:  # 10KB máximo
            await update.message.reply_text('❌ Archivo demasiado grande (máx 10KB)')
            return
        
        # Descargar y validar cookies
        await (await doc.get_file()).download_to_drive(cookies_path)
        
        with open(cookies_path, 'r') as f:
            cookies_content = f.read()
            if 'youtube.com' not in cookies_content:
                os.remove(cookies_path)
                await update.message.reply_text('❌ Cookies inválidas: No contienen datos de YouTube')
                return
                
        await update.message.reply_text('✅ Cookies actualizadas correctamente!')
        logger.info(f"Cookies actualizadas por {update.effective_user.id}")
        
    except Exception as e:
        await update.message.reply_text(f'❌ Error: {str(e)}')
        if os.path.exists(cookies_path):
            os.remove(cookies_path)

def help_command(update: Update, context: CallbackContext) -> None:
    """Muestra los comandos disponibles."""
    if not is_authorized(update.effective_user.id):
        update.message.reply_text('No autorizado.')
        return

    update.message.reply_text(
        '📖 *Comandos disponibles:*\n\n'
        '/start - Mostrar mensaje de bienvenida\n'
        '/help - Mostrar esta ayuda\n'
        '/download <url> - Descargar video de YouTube\n'
        '/upload <file_path> - Subir archivo\n'
        '/list [path] - Listar archivos\n'
        '/clean - Limpiar archivos temporales\n'
        '/status - Ver estado del servidor',
        parse_mode='Markdown'
    )

async def send_startup_message(context: ContextTypes.DEFAULT_TYPE):
    """Envía mensaje de inicio usando el contexto correcto."""
    for user_id in AUTHORIZED_USERS:
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    "✅ *Bot iniciado correctamente*\\.\n\n"
                    "📖 *Comandos disponibles:*\n\n"
                    "/start \\- Mostrar mensaje de bienvenida\n"
                    "/help \\- Mostrar ayuda\n"
                    "/download <url> \\- Descargar video de YouTube\n"
                    "/upload <file\\_path> \\- Subir archivo\n"
                    "/list \\[path\\] \\- Listar archivos\n"
                    "/clean \\- Limpiar temporales\n"
                    "/status \\- Estado del servidor"
                ),
                parse_mode='MarkdownV2'
            )
        except Exception as e:
            logger.error(f"Error enviando mensaje a {user_id}: {e}")

async def post_init(application):
    """Tareas posteriores a la inicialización."""
    await send_startup_message(application)

async def upload_large_file(update: Update, context: CallbackContext, file_path: str, caption: str = "") -> bool:
    """Sube archivos grandes usando el bot del contexto."""
    try:
        file_size = os.path.getsize(file_path)
        filename = os.path.basename(file_path)
        
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id, 
            action=ChatAction.UPLOAD_DOCUMENT
        )
        
        await update.message.reply_text(f"⚡ Subiendo {filename}...")
        
        with open(file_path, 'rb') as file:
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=InputFile(file, filename=filename),
                caption=caption,
                read_timeout=UPLOAD_TIMEOUT,
                write_timeout=UPLOAD_TIMEOUT,
                connect_timeout=UPLOAD_TIMEOUT
            )
        return True
        
    except Exception as e:
        logger.error(f"Error subiendo {filename}: {e}")
        raise

async def upload_file(update: Update, context: CallbackContext) -> None:
    """Maneja la subida de archivos con gestión asíncrona completa."""
    try:
        if not is_authorized(update.effective_user.id):
            await update.message.reply_text('No autorizado.')
            return
        
        if not context.args:
            await update.message.reply_text('Ejemplo: /upload /ruta/al/archivo.mkv')
            return
        
        file_path = ' '.join(context.args)
        
        if not os.path.exists(file_path):
            await update.message.reply_text(f'❌ Archivo no encontrado: {file_path}')
            return

        file_size = os.path.getsize(file_path)
        filename = os.path.basename(file_path)
        
        if file_size > MAX_FILE_SIZE:
            await update.message.reply_text(f'✂️ Dividiendo archivo de {file_size/1024/1024:.2f} MB...')
            parts = split_large_file(file_path)
            
            await update.message.reply_text(f'📦 {len(parts)} partes creadas. Iniciando subida...')
            
            for i, part in enumerate(parts, 1):
                try:
                    await upload_large_file(update, context, part, f'Parte {i}/{len(parts)} de {filename}')
                    await update.message.reply_text(f'✅ Parte {i} subida')
                except Exception as e:
                    await update.message.reply_text(f'❌ Error en parte {i}: {str(e)}')
                    raise
                    
            await update.message.reply_text('🎉 Todas las partes subidas exitosamente!')
            
        else:
            await upload_large_file(update, context, file_path, f'Archivo completo: {filename}')
            await update.message.reply_text('✅ Subida completada')
            
    except Exception as e:
        await update.message.reply_text(f'❌ Error crítico: {str(e)}')
        logger.error(f"Error en upload_file: {e}", exc_info=True)

def main():
    """Configuración principal del bot."""
    application = ApplicationBuilder() \
        .token(TOKEN) \
        .http_version('1.1') \
        .get_updates_http_version('1.1') \
        .post_init(post_init) \
        .build()

    # Handlers
    handlers = [
        CommandHandler("upload", upload_file)
    ]

    # Manejo de errores global
    application.add_error_handler(error_handler)
    
    for handler in handlers:
        application.add_handler(handler)

    # Ejecutar el bot
    application.run_polling()

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Maneja errores no capturados."""
    logger.error("Excepción no capturada:", exc_info=context.error)
    
    if isinstance(update, Update):
        await update.message.reply_text(f'⚠️ Error interno: {context.error}')

if __name__ == "__main__":
    main()