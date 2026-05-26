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
            self._users: dict[str, str] = {}  # FIXED-P1: 多用户认证字典
            self._initialized = False

        async def authenticate(self, session: Session) -> bool:
            if not self._initialized:
                self._username = self.auth_config.get("username", "")
                self._password = self.auth_config.get("password", "")
                self._users = self.auth_config.get("users", {})  # FIXED-P1: 读取多用户配置
                self._initialized = True
            if not session.username:
                logger.debug("MQTT auth: no username provided, rejecting")
                return False
            # FIXED-P1: 优先匹配多用户字典
            if self._users and session.username in self._users:
                expected = self._users[session.username]
                if session.password is not None and session.password.decode("utf-8", errors="replace") == expected:
                    logger.info("MQTT auth: user '%s' authenticated", session.username)
                    return True
                logger.warning("MQTT auth: user '%s' password mismatch", session.username)
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
except Exception as e:  # FIXED-P1: 捕获非ImportError异常并记录，避免吞没系统信号
    logger.warning("MQTT auth plugin load error: %s", e)
