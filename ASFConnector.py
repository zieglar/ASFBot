import logger
from IPCProtocol import IPCProtocolHandler
from urllib.parse import quote

class ASFConnector:

    def __init__(self, host='127.0.0.1', port='1242', path='/Api', password=None,
                 connect_timeout=IPCProtocolHandler.DEFAULT_CONNECT_TIMEOUT,
                 read_timeout=IPCProtocolHandler.DEFAULT_READ_TIMEOUT):
        self.log = logger.get_logger(__name__)

        self.host = host
        self.port = port
        self.path = path

        self.log.debug("ASF connector initialized")
        self.connection_handler = IPCProtocolHandler(
            host,
            port,
            path,
            password,
            connect_timeout=connect_timeout,
            read_timeout=read_timeout,
        )

    def get_asf_info(self):
        """" Fetches common info related to ASF as a whole. """
        return self.connection_handler.get('/ASF')

    def get_bot_info(self, bot):
        """ Fetches common info related to given bots. """
        bot_selector = _encoded_bot_selector(bot)
        resource = '/Bot/' + bot_selector
        response = self.connection_handler.get(resource)
        if not isinstance(response, dict):
            return 'Getting bot info failed: Invalid ASF response.'
        results = response.get('Result')
        if isinstance(results, dict) and results:
            message = ""
            for bot_name, bot_data in results.items():
                message += 'Bot {}: '.format(bot_name)
                if not isinstance(bot_data, dict):
                    message += 'Invalid ASF response.\n'
                    continue
                if bot_data.get('IsConnectedAndLoggedOn', False):
                    cards_farmer = bot_data.get('CardsFarmer')
                    if not isinstance(cards_farmer, dict):
                        cards_farmer = {}
                    farm_message = ""
                    if cards_farmer.get('Paused', False):
                        farm_message += 'Farming paused.'
                    current_games = cards_farmer.get('CurrentGamesFarming', [])
                    if not isinstance(current_games, list):
                        current_games = []
                    if not farm_message and current_games:
                        farm_message += 'Currently farming games:'
                    for current_game in current_games:
                        if not isinstance(current_game, dict):
                            continue
                        appid = current_game.get('AppID', 'unknown')
                        appname = current_game.get('GameName', 'Unknown')
                        cards_remaining = current_game.get('CardsRemaining', 'unknown')
                        farm_message += '\n\t[{}/{}] {} cards remaining.'.format(appid, appname, cards_remaining)
                    games_to_farm = cards_farmer.get('GamesToFarm', [])
                    if not isinstance(games_to_farm, list):
                        games_to_farm = []
                    if games_to_farm:
                        games = []
                        for game in games_to_farm:
                            if isinstance(game, dict):
                                games.append('[{}/{}]'.format(
                                    game.get('AppID', 'unknown'),
                                    game.get('GameName', 'Unknown'),
                                ))
                        if games:
                            farm_message += ' {} game(s) to farm ({}). '.format(len(games), ' '.join(games))
                    time_remaining = cards_farmer.get('TimeRemaining', '00:00:00')
                    if time_remaining and time_remaining != '00:00:00':
                        farm_message += 'Time remaining: {}'.format(time_remaining)
                    if len(farm_message) == 0:
                        farm_message += 'Idle.'
                    message += farm_message + '\n'
                else:
                    if 'BotConfig' in bot_data and not bot_data['BotConfig']:
                        message += 'Not configured.\n'
                    else:
                        message += 'Offline.\n'
        elif response.get('Success', False):
            message = 'Bot {} not found.'.format(bot)
        else:
            message = 'Getting bot info failed: {}'.format(response.get('Message', 'Unknown error'))
        return message

    def bot_redeem(self, bot, keys):
        """ Redeems cd-keys on given bot. """
        bot_selector = _encoded_bot_selector(bot)
        payload_keys = _validated_keys(keys)
        resource = '/Bot/' + bot_selector + '/Redeem'
        data = {'KeysToRedeem': payload_keys}
        response = self.connection_handler.post(resource, payload=data)
        if not isinstance(response, dict):
            return 'Redeem failed: Invalid ASF response.'
        results = response.get('Result')
        if isinstance(results, dict) and results:
            messages = []
            for bot_name, bot_results in results.items():
                if not isinstance(bot_results, dict) or not bot_results:
                    messages.append('Bot {}: Invalid ASF response.'.format(bot_name))
                    continue
                for key, details in bot_results.items():
                    messages.append(_format_redeem_result(bot_name, key, details))
            message = '\n'.join(messages)
        elif response.get('Success', False):
            message = 'Bot {} not found.'.format(bot)
        else:
            message = 'Redeem failed: {}'.format(response.get('Message', 'Unknown error'))
        return message

    def send_command(self, command):
        """
        This API endpoint is supposed to be entirely replaced by ASF actions available under /Api/ASF/{action} and /Api/Bot/{bot}/{action}.
        You should use “given bot” commands when executing this endpoint, omitting targets of the command will cause the command to be executed on first defined bot
        """
        if not isinstance(command, str):
            raise TypeError('"command" must be a string')
        if not command.strip():
            raise ValueError('"command" must not be empty')
        resource = '/Command/'
        data = {"Command": command}
        response = self.connection_handler.post(resource, payload=data)
        if not isinstance(response, dict):
            return 'Command unsuccessful: Invalid ASF response.'
        message = ""
        if response.get('Success', False):
            message += str(response.get('Result', ''))
        else:
            message += 'Command unsuccessful: {}'.format(response.get('Message', 'Unknown error'))

        return message


def _encoded_bot_selector(bot):
    if not isinstance(bot, str):
        raise TypeError('"bot" must be a string')
    names = bot.split(',')
    if not names or any(not name.strip() for name in names):
        raise ValueError('"bot" must contain non-empty names')
    for name in names:
        if any(char in name for char in '/\\?#') or any(ord(char) < 32 for char in name):
            raise ValueError('"bot" contains unsafe characters')
    return ','.join(quote(name, safe='-._~*') for name in names)


def _validated_keys(keys):
    if isinstance(keys, str):
        key_values = [keys]
    elif isinstance(keys, set):
        key_values = list(keys)
    else:
        raise TypeError('"keys" must be a string or set')
    if not key_values or any(not isinstance(key, str) for key in key_values):
        raise ValueError('"keys" must contain non-empty strings')
    if any(not key.strip() or any(ord(char) < 32 for char in key) for key in key_values):
        raise ValueError('"keys" must contain valid non-empty strings')
    return sorted(key_values)


def _enum_name(mapping, value):
    if isinstance(value, str):
        return value
    if isinstance(value, bool) or not isinstance(value, int):
        return 'Unknown value'
    return mapping.get(value, 'Unknown ({})'.format(value))


def _format_redeem_result(bot_name, key, details):
    if not isinstance(details, dict):
        return 'Bot {}: [{}] Invalid ASF response.'.format(bot_name, key)
    receipt = details.get('purchase_receipt_info')
    if isinstance(receipt, dict):
        line_items = receipt.get('line_items')
        items = []
        if isinstance(line_items, list):
            for item in line_items:
                if isinstance(item, dict):
                    items.append('[{}, {}]'.format(
                        item.get('packageid', 'unknown'),
                        item.get('line_item_description', 'Unknown'),
                    ))
        return 'Bot {}: [{}] {}: {}/{}'.format(
            bot_name, key, ' '.join(items),
            _enum_name(Result, receipt.get('purchase_status')),
            _enum_name(PurchaseResultDetail, receipt.get('result_detail')),
        )
    if 'Result' not in details and 'PurchaseResultDetail' not in details:
        return 'Bot {}: [{}] Invalid ASF response.'.format(bot_name, key)
    return 'Bot {}: [{}] {}/{}'.format(
        bot_name, key,
        _enum_name(Result, details.get('Result')),
        _enum_name(PurchaseResultDetail, details.get('PurchaseResultDetail')),
    )


PurchaseResultDetail = {
    0: 'NoDetail',
    1: 'AVSFailure',
    2: 'InsufficientFunds',
    3: 'ContactSupport',
    4: 'Timeout',
    5: 'InvalidPackage',
    6: 'InvalidPaymentMethod',
    7: 'InvalidData',
    8: 'OthersInProgress',
    9: 'AlreadyPurchased',
    10: 'WrongPrice',
    11: 'FraudCheckFailed',
    12: 'CancelledByUser',
    13: 'RestrictedCountry',
    14: 'BadActivationCode',
    15: 'DuplicateActivationCode',
    16: 'UseOtherPaymentMethod',
    17: 'UseOtherFunctionSource',
    18: 'InvalidShippingAddress',
    19: 'RegionNotSupported',
    20: 'AcctIsBlocked',
    21: 'AcctNotVerified',
    22: 'InvalidAccount',
    23: 'StoreBillingCountryMismatch',
    24: 'DoesNotOwnRequiredApp',
    25: 'CanceledByNewTransaction',
    26: 'ForceCanceledPending',
    27: 'FailCurrencyTransProvider',
    28: 'FailedCyberCafe',
    29: 'NeedsPreApproval',
    30: 'PreApprovalDenied',
    31: 'WalletCurrencyMismatch',
    32: 'EmailNotValidated',
    33: 'ExpiredCard',
    34: 'TransactionExpired',
    35: 'WouldExceedMaxWallet',
    36: 'MustLoginPS3AppForPurchase',
    37: 'CannotShipToPOBox',
    38: 'InsufficientInventory',
    39: 'CannotGiftShippedGoods',
    40: 'CannotShipInternationally',
    41: 'BillingAgreementCancelled',
    42: 'InvalidCoupon',
    43: 'ExpiredCoupon',
    44: 'AccountLocked',
    45: 'OtherAbortableInProgress',
    46: 'ExceededSteamLimit',
    47: 'OverlappingPackagesInCart',
    48: 'NoWallet',
    49: 'NoCachedPaymentMethod',
    50: 'CannotRedeemCodeFromClient',
    51: 'PurchaseAmountNoSupportedByProvider',
    52: 'OverlappingPackagesInPendingTransaction',
    53: 'RateLimited',
    54: 'OwnsExcludedApp',
    55: 'CreditCardBinMismatchesType',
    56: 'CartValueTooHigh',
    57: 'BillingAgreementAlreadyExists',
    58: 'POSACodeNotActivated',
    59: 'CannotShipToCountry',
    60: 'HungTransactionCancelled',
    61: 'PaypalInternalError',
    62: 'UnknownGlobalCollectError',
    63: 'InvalidTaxAddress',
    64: 'PhysicalProductLimitExceeded',
    65: 'PurchaseCannotBeReplayed',
    66: 'DelayedCompletion',
    67: 'BundleTypeCannotBeGifted'
}

Result = {
    0: 'Invalid',
    1: 'OK',
    2: 'Fail',
    3: 'NoConnection',
    4: 'InvalidPassword',
    5: 'LoggedInElsewhere',
    6: 'InvalidProtocolVer',
    7: 'InvalidParam',
    8: 'FileNotFound',
    9: 'Busy',
    10: 'InvalidState',
    11: 'InvalidName',
    12: 'InvalidEmail',
    13: 'DuplicateName',
    14: 'AccessDenied',
    15: 'Timeout',
    16: 'Banned',
    17: 'AccountNotFound',
    18: 'InvalidSteamID',
    19: 'ServiceUnavailable',
    20: 'NotLoggedOn',
    21: 'Pending',
    22: 'EncryptionFailure',
    23: 'InsufficientPrivilege',
    24: 'LimitExceeded',
    25: 'Revoked',
    26: 'Expired',
    27: 'AlreadyRedeemed',
    28: 'DuplicateRequest',
    29: 'AlreadyOwned',
    30: 'IPNotFound',
    31: 'PersistFailed',
    32: 'LockingFailed',
    33: 'LogonSessionReplaced',
    34: 'ConnectFailed',
    35: 'HandshakeFailed',
    36: 'IOFailure',
    37: 'RemoteDisconnect',
    38: 'ShoppingCartNotFound',
    39: 'Blocked',
    40: 'Ignored',
    41: 'NoMatch',
    42: 'AccountDisabled',
    43: 'ServiceReadOnly',
    44: 'AccountNotFeatured',
    45: 'AdministratorOK',
    46: 'ContentVersion',
    47: 'TryAnotherCM',
    48: 'PasswordRequiredToKickSession',
    49: 'AlreadyLoggedInElsewhere',
    50: 'Suspended',
    51: 'Cancelled',
    52: 'DataCorruption',
    53: 'DiskFull',
    54: 'RemoteCallFailed',
    55: 'PasswordUnset',
    56: 'ExternalAccountUnlinked',
    57: 'PSNTicketInvalid',
    58: 'ExternalAccountAlreadyLinked',
    59: 'RemoteFileConflict',
    60: 'IllegalPassword',
    61: 'SameAsPreviousValue',
    62: 'AccountLogonDenied',
    63: 'CannotUseOldPassword',
    64: 'InvalidLoginAuthCode',
    65: 'AccountLogonDeniedNoMail',
    66: 'HardwareNotCapableOfIPT',
    67: 'IPTInitError',
    68: 'ParentalControlRestricted',
    69: 'FacebookQueryError',
    70: 'ExpiredLoginAuthCode',
    71: 'IPLoginRestrictionFailed',
    72: 'AccountLockedDown',
    73: 'AccountLogonDeniedVerifiedEmailRequired',
    74: 'NoMatchingURL',
    75: 'BadResponse',
    76: 'RequirePasswordReEntry',
    77: 'ValueOutOfRange',
    78: 'UnexpectedError',
    79: 'Disabled',
    80: 'InvalidCEGSubmission',
    81: 'RestrictedDevice',
    82: 'RegionLocked',
    83: 'RateLimitExceeded',
    84: 'AccountLoginDeniedNeedTwoFactor',
    85: 'ItemDeleted',
    86: 'AccountLoginDeniedThrottle',
    87: 'TwoFactorCodeMismatch',
    88: 'TwoFactorActivationCodeMismatch',
    89: 'AccountAssociatedToMultiplePartners',
    90: 'NotModified',
    91: 'NoMobileDevice',
    92: 'TimeNotSynced',
    93: 'SMSCodeFailed',
    94: 'AccountLimitExceeded',
    95: 'AccountActivityLimitExceeded',
    96: 'PhoneActivityLimitExceeded',
    97: 'RefundToWallet',
    98: 'EmailSendFailure',
    99: 'NotSettled',
    100: 'NeedCaptcha',
    101: 'GSLTDenied',
    102: 'GSOwnerDenied',
    103: 'InvalidItemType',
    104: 'IPBanned',
    105: 'GSLTExpired',
    106: 'InsufficientFunds',
    107: 'TooManyPending',
    108: 'NoSiteLicensesFound',
    109: 'WGNetworkSendExceeded',
    110: 'AccountNotFriends',
    111: 'LimitedUserAccount'
}
