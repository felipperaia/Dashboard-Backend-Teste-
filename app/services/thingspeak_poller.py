"""
services/thingspeak_poller.py
Serviço para buscar dados do ThingSpeak periodicamente.
"""
import asyncio
import logging
from .thing_speak import fetch_and_store
from .. import config

logger = logging.getLogger("uvicorn.error")

async def thingspeak_poller():
    """
    Tarefa em segundo plano para buscar dados do ThingSpeak em intervalos regulares.
    """
    while True:
        try:
            # Verificar se as configurações existem
            if not config.THINGSPEAK_API_KEYS:
                logger.warning("THINGSPEAK_API_KEYS não configurado")
                await asyncio.sleep(300)
                continue
                
            # Buscar dados de todos os canais configurados
            for system_channel_id, read_key in config.THINGSPEAK_API_KEYS.items():
                try:
                    # Obter channel_id do ThingSpeak a partir do mapeamento
                    if (config.THINGSPEAK_CHANNELS and 
                        system_channel_id in config.THINGSPEAK_CHANNELS):
                        thing_channel_id = config.THINGSPEAK_CHANNELS[system_channel_id]
                    else:
                        logger.error(f"Channel {system_channel_id} não encontrado em THINGSPEAK_CHANNELS")
                        continue
                    
                    # Usar o ID real do ThingSpeak (não o ID do sistema)
                    await fetch_and_store(
                        channel_id=thing_channel_id,  # ID do ThingSpeak (3082805)
                        read_key=read_key,
                        silo_id=system_channel_id  # ID do sistema ("1")
                    )
                except Exception as e:
                    logger.error(f"Erro ao processar canal {system_channel_id}: {e}")
                    continue
                    
            # Esperar 5 minutos entre as verificações
            await asyncio.sleep(300)
        except Exception as e:
            logger.error(f"Erro no poller do ThingSpeak: {e}")
            await asyncio.sleep(60)