import os
import logging
import subprocess
import requests
from telegram.ext import Application
from telegram import Update, InputFile
from telegram.ext import Updater, CommandHandler, MessageHandler, filters, CallbackContext

# Configuración
TOKEN = os.getenv("YT_TELEGRAM_BOT") 
AUTHORIZED_USERS = os.getenv("MY_TELEGRAM_ID")
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

def download_video(update: Update, context: CallbackContext) -> None:
    """Descarga un video de YouTube usando yt-dlp."""
    if not is_authorized(update.effective_user.id):
        update.message.reply_text('No autorizado.')
        return
    
    if not context.args:
        update.message.reply_text('Por favor proporciona una URL. Ejemplo: /download https://youtu.be/ejemplo')
        return
    
    url = ' '.join(context.args)
    ensure_temp_dir()
    
    try:
        update.message.reply_text(f'⏬ Descargando video de {url}...')
        
        # Configuración de yt-dlp para archivos grandes
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
        
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = process.communicate()
        
        if process.returncode != 0:
            raise Exception(f'Error en yt-dlp: {stderr.decode()}')
        
        # Encontrar el archivo descargado
        downloaded_files = [f for f in os.listdir(TEMP_DIR) if f.endswith('.mkv')]
        if not downloaded_files:
            raise Exception('No se pudo encontrar el archivo descargado.')
        
        filename = max(
            [os.path.join(TEMP_DIR, f) for f in downloaded_files],
            key=os.path.getctime
        )
        
        update.message.reply_text(
            f'✅ Descarga completada: {os.path.basename(filename)}\n'
            f'📏 Tamaño: {os.path.getsize(filename)/1024/1024:.2f} MB\n'
            f'Usa /upload {filename} para subirlo.'
        )
        
    except Exception as e:
        update.message.reply_text(f'❌ Error al descargar: {str(e)}')
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

def upload_large_file(update: Update, file_path: str, caption: str = ""):
    """Sube archivos grandes usando la API de Telegram con multipart/form-data"""
    bot = update.message.bot
    file_size = os.path.getsize(file_path)
    filename = os.path.basename(file_path)
    
    try:
        if file_size > 50 * 1024 * 1024:  # Si es mayor a 50MB
            update.message.reply_text(f"⚡ Preparando subida de archivo grande ({file_size/1024/1024:.2f} MB)...")
            
            # Configurar la URL de la API
            api_url = f"https://api.telegram.org/bot{TOKEN}/sendDocument"
            
            # Leer el archivo en chunks
            with open(file_path, 'rb') as file:
                files = {'document': (filename, file)}
                data = {'chat_id': update.message.chat_id, 'caption': caption}
                
                response = requests.post(
                    api_url,
                    files=files,
                    data=data,
                    timeout=UPLOAD_TIMEOUT,
                    headers={'Connection': 'keep-alive'}
                )
                
                if response.status_code != 200:
                    error_msg = response.json().get('description', 'Error desconocido')
                    raise Exception(f"API Error: {error_msg}")
                
                return True
        else:
            # Para archivos pequeños usar el método normal
            with open(file_path, 'rb') as file:
                bot.send_document(
                    chat_id=update.message.chat_id,
                    document=InputFile(file, filename=filename),
                    caption=caption,
                    read_timeout=UPLOAD_TIMEOUT,
                    write_timeout=UPLOAD_TIMEOUT,
                    connect_timeout=UPLOAD_TIMEOUT
                )
            return True
    
    except Exception as e:
        logger.error(f"Error en upload_large_file: {e}")
        raise

def upload_file(update: Update, context: CallbackContext) -> None:
    """Sube un archivo, dividiéndolo si es necesario."""
    if not is_authorized(update.effective_user.id):
        update.message.reply_text('No autorizado.')
        return
    
    if not context.args:
        update.message.reply_text('Por favor especifica un archivo. Ejemplo: /upload /ruta/al/archivo.mkv')
        return
    
    file_path = ' '.join(context.args)
    
    if not os.path.exists(file_path):
        update.message.reply_text(f'❌ El archivo {file_path} no existe.')
        return
    
    file_size = os.path.getsize(file_path)
    filename = os.path.basename(file_path)
    
    try:
        if file_size > MAX_FILE_SIZE:
            # Archivo demasiado grande, necesitamos dividirlo
            update.message.reply_text(
                f'📦 El archivo es muy grande ({file_size/1024/1024:.2f} MB). '
                'Dividiendo en partes...'
            )
            
            parts = split_large_file(file_path)
            total_parts = len(parts)
            
            update.message.reply_text(
                f'✂️ Dividido en {total_parts} partes. Comenzando subida...'
            )
            
            for i, part in enumerate(parts, 1):
                try:
                    upload_large_file(update, part, f'Parte {i}/{total_parts} de {filename}')
                    update.message.reply_text(f'✅ Parte {i}/{total_parts} subida correctamente.')
                except Exception as e:
                    update.message.reply_text(f'❌ Error al subir parte {i}: {str(e)}')
                    raise
            
            update.message.reply_text('🎉 Todas las partes subidas correctamente.')
        else:
            # Subir archivo normal
            upload_large_file(update, file_path, f'Archivo completo: {filename}')
            update.message.reply_text('✅ Archivo subido correctamente.')
        
        logger.info(f"Archivo {filename} subido por {update.effective_user.id}")
    
    except Exception as e:
        update.message.reply_text(f'❌ Error al subir el archivo: {str(e)}')
        logger.error(f"Error al subir {filename}: {e}")

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
    """Guarda el archivo de cookies enviado por el usuario."""
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text('No autorizado.')
        return
    
    if not update.message.document:
        await update.message.reply_text('Por favor envía un archivo cookies.txt')
        return
    
    if not update.message.document.file_name.endswith('.txt'):
        await update.message.reply_text('El archivo debe ser un .txt')
        return
    
    try:
        ensure_temp_dir()
        cookies_file = await update.message.document.get_file()
        cookies_path = os.path.join(TEMP_DIR, 'cookies.txt')
        await cookies_file.download_to_drive(cookies_path)
        await update.message.reply_text('🍪 Archivo de cookies actualizado correctamente!')
    except Exception as e:
        await update.message.reply_text(f'❌ Error al guardar cookies: {str(e)}')
        logger.error(f"Error al guardar cookies: {e}")

def main() -> None:
    """Inicia el bot usando la nueva API de python-telegram-bot v20+"""
    # Crea la aplicación con tu token
    application = Application.builder().token(TOKEN).build()

    # Añade los handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("download", download_video))
    application.add_handler(CommandHandler("upload", upload_file))
    application.add_handler(CommandHandler("list", list_files))
    application.add_handler(CommandHandler("clean", clean_temp))
    application.add_handler(CommandHandler("status", server_status))
    application.add_handler(MessageHandler(filters.document, handle_cookies))

    # Inicia el bot
    ensure_temp_dir()
    logger.info("Bot iniciado y listo para recibir comandos")
    application.run_polling()
    """Inicia el bot."""
    updater = Updater(TOKEN)
    dispatcher = updater.dispatcher

    # Manejadores de comandos
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("download", download_video))
    dispatcher.add_handler(CommandHandler("upload", upload_file))
    dispatcher.add_handler(CommandHandler("list", list_files))
    dispatcher.add_handler(CommandHandler("clean", clean_temp))
    dispatcher.add_handler(CommandHandler("status", server_status))

    # Iniciar el bot
    ensure_temp_dir()
    updater.start_polling()
    logger.info("Bot iniciado y listo para recibir comandos")
    updater.idle()

if __name__ == '__main__':
    main()