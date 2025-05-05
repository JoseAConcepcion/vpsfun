import os
import logging
import rarfile 
import zipfile
import tarfile
import py7zr
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

# Configuración básica
load_dotenv()
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
ALLOWED_USERS = set()  # Usamos un set para evitar duplicados

# Configurar logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Mensaje de bienvenida cuando se usa /start"""
    user = update.effective_user
    await update.message.reply_text(
        f'Hola {user.first_name}! Envíame un archivo comprimido (.zip, .rar, etc.) y lo descomprimiré para ti.'
    )

async def add_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Añade un usuario a la lista de permitidos (/adduser <id>)"""
    if not context.args:
        await update.message.reply_text("Uso: /adduser <user_id>")
        return
    
    try:
        user_id = int(context.args[0])
        ALLOWED_USERS.add(user_id)
        await update.message.reply_text(f"Usuario {user_id} añadido correctamente")
    except ValueError:
        await update.message.reply_text("El ID debe ser un número")

async def handle_compressed_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Maneja los archivos comprimidos recibidos"""
    # Verificar si el usuario está permitido
    if ALLOWED_USERS and update.effective_user.id not in ALLOWED_USERS:
        await update.message.reply_text("⚠️ Lo siento, no tienes permiso para usar este bot.")
        return
    
    # Obtener el archivo
    file = await update.message.document.get_file()
    file_name = update.message.document.file_name
    
    if not file_name:
        await update.message.reply_text("El archivo no tiene nombre.")
        return
    
    # Verificar que sea un archivo comprimido
    valid_extensions = ('.zip', '.rar', '.7z', '.tar', '.gz', '.bz2')
    if not file_name.lower().endswith(valid_extensions):
        await update.message.reply_text("Por favor envía un archivo comprimido (.zip, .rar, .7z, etc.)")
        return
    
    # Crear directorio temporal
    user_dir = f"temp_{update.effective_user.id}"
    os.makedirs(user_dir, exist_ok=True)
    
    # Descargar el archivo
    file_path = os.path.join(user_dir, file_name)
    await file.download_to_drive(file_path)
    
    await update.message.reply_text(f"Archivo {file_name} recibido. Descomprimiendo...")
    
    try:
        extract_dir = os.path.join(user_dir, "extracted")
        os.makedirs(extract_dir, exist_ok=True)
        
        # Determinar el tipo de archivo y descomprimir
        if file_name.lower().endswith('.zip'):
            with zipfile.ZipFile(file_path, 'r') as z:
                z.extractall(extract_dir)
        
        elif file_name.lower().endswith('.tar.gz') or file_name.lower().endswith('.tgz'):
            with tarfile.open(file_path, 'r:gz') as tar:
                tar.extractall(extract_dir)
        
        elif file_name.lower().endswith('.tar.bz2'):
            with tarfile.open(file_path, 'r:bz2') as tar:
                tar.extractall(extract_dir)
        
        elif file_name.lower().endswith('.7z'):
            with py7zr.SevenZipFile(file_path, mode='r') as z:
                z.extractall(extract_dir)
        
        elif file_name.lower().endswith('.rar'):
            with rarfile.RarFile(file_path) as rf:
                rf.extractall(extract_dir)
        else:
            await update.message.reply_text("Formato de archivo no soportado")
            return
        
        await send_extracted_files(update, context, extract_dir)
        await update.message.reply_text("✅ Descompresión completada!")
    
    except Exception as e:
        logger.error(f"Error al descomprimir: {e}")
        await update.message.reply_text(f"❌ Error al descomprimir: {str(e)}")
    
    finally:
        clean_temp_files(user_dir)
async def send_extracted_files(update: Update, context: ContextTypes.DEFAULT_TYPE, directory: str):
    """Envía los archivos descomprimidos al usuario"""
    for root, _, files in os.walk(directory):
        for file in files:
            file_path = os.path.join(root, file)
            try:
                await update.message.reply_document(
                    document=file_path,
                    filename=file
                )
            except Exception as e:
                logger.error(f"Error al enviar archivo {file}: {e}")
                await update.message.reply_text(f"No se pudo enviar el archivo {file}")

def clean_temp_files(directory: str):
    """Elimina los archivos temporales"""
    try:
        for root, dirs, files in os.walk(directory, topdown=False):
            for file in files:
                os.remove(os.path.join(root, file))
            for dir in dirs:
                os.rmdir(os.path.join(root, dir))
        os.rmdir(directory)
    except Exception as e:
        logger.error(f"Error al limpiar archivos temporales: {e}")

def main() -> None:
    """Inicia el bot"""
    application = Application.builder().token(TOKEN).build()

    # Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("adduser", add_user))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_compressed_file))

    # Iniciar el bot
    application.run_polling()

if __name__ == '__main__':
    main()