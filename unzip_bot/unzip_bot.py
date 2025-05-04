import os
import logging
from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext

load_dotenv()

# Reemplaza la línea del token con:
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
ALLOWED_USERS = []  # Lista de IDs de usuarios permitidos (dejar vacío para permitir a todos)

# Configurar logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def start(update: Update, context: CallbackContext) -> None:
    """Mensaje de bienvenida cuando se usa /start"""
    user = update.effective_user
    update.message.reply_text(
        f'Hola {user.first_name}! Envíame un archivo comprimido (.zip, .rar, etc.) y lo descomprimiré para ti.'
    )

def handle_compressed_file(update: Update, context: CallbackContext) -> None:
    """Maneja los archivos comprimidos recibidos"""
    # Verificar si el usuario está permitido (si hay lista de permitidos)
    if ALLOWED_USERS and update.effective_user.id not in ALLOWED_USERS:
        update.message.reply_text("Lo siento, no tienes permiso para usar este bot.")
        return
    
    # Obtener el archivo
    file = update.message.document or update.message.effective_attachment
    if not file:
        update.message.reply_text("No se pudo obtener el archivo.")
        return
    
    file_name = file.file_name
    if not file_name:
        update.message.reply_text("El archivo no tiene nombre.")
        return
    
    # Verificar que sea un archivo comprimido
    valid_extensions = ('.zip', '.rar', '.7z', '.tar', '.gz', '.bz2')
    if not file_name.lower().endswith(valid_extensions):
        update.message.reply_text("Por favor envía un archivo comprimido (.zip, .rar, .7z, etc.)")
        return
    
    # Crear directorio temporal
    user_dir = f"temp_{update.effective_user.id}"
    os.makedirs(user_dir, exist_ok=True)
    
    # Descargar el archivo
    file_path = os.path.join(user_dir, file_name)
    file_obj = context.bot.get_file(file.file_id)
    file_obj.download(file_path)
    
    update.message.reply_text(f"Archivo {file_name} recibido. Descomprimiendo...")
    
    try:
        # Descomprimir con 7z
        extract_dir = os.path.join(user_dir, "extracted")
        os.makedirs(extract_dir, exist_ok=True)
        
        # Comando 7z (puede variar según tu sistema)
        cmd = f'7z x "{file_path}" -o"{extract_dir}" -y'
        os.system(cmd)
        
        # Enviar archivos descomprimidos
        send_extracted_files(update, context, extract_dir)
        
        update.message.reply_text("¡Descompresión completada!")
    except Exception as e:
        logger.error(f"Error al descomprimir: {e}")
        update.message.reply_text(f"Error al descomprimir el archivo: {e}")
    finally:
        # Limpiar archivos temporales (opcional)
        clean_temp_files(user_dir)

def send_extracted_files(update: Update, context: CallbackContext, directory: str):
    """Envía los archivos descomprimidos al usuario"""
    for root, _, files in os.walk(directory):
        for file in files:
            file_path = os.path.join(root, file)
            try:
                with open(file_path, 'rb') as f:
                    context.bot.send_document(
                        chat_id=update.effective_chat.id,
                        document=f,
                        filename=file
                    )
            except Exception as e:
                logger.error(f"Error al enviar archivo {file}: {e}")
                update.message.reply_text(f"No se pudo enviar el archivo {file}")

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
    updater = Updater(TOKEN)
    dispatcher = updater.dispatcher

    # Handlers
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(MessageHandler(Filters.document, handle_compressed_file))

    # Iniciar el bot
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()