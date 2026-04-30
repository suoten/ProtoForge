import logging

logger = logging.getLogger(__name__)

try:
    from amqtt.contexts import Action
    from amqtt.plugins.authentication import BaseAuthPlugin
    from amqtt.session import Session

    class MqttAuthPlugin(BaseAuthPlugin):
        def __init__(self, context):
            super().__init__(context)
            self._username = ""
            self._password = ""

        async def authenticate(self, session: Session) -> bool:
            if not self._username:
                self._username = self.auth_config.get("username", "")
                self._password = self.auth_config.get("password", "")
            if not session.username:
                logger.debug("MQTT auth: no username provided, rejecting")
                return False
            if session.username == self._username:
                if session.password is not None and session.password.decode("utf-8", errors="replace") == self._password:
                    logger.info("MQTT auth: user '%s' authenticated", session.username)
                    return True
                logger.warning("MQTT auth: user '%s' password mismatch", session.username)
                return False
            logger.warning("MQTT auth: unknown user '%s'", session.username)
            return False

except ImportError:
    pass
