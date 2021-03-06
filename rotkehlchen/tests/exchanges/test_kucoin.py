import warnings as test_warnings
from contextlib import ExitStack
from http import HTTPStatus
from json.decoder import JSONDecodeError
from unittest.mock import patch

import pytest
import requests

from rotkehlchen.accounting.structures import Balance
from rotkehlchen.assets.asset import Asset
from rotkehlchen.assets.converters import UNSUPPORTED_KUCOIN_ASSETS, asset_from_kucoin
from rotkehlchen.errors import RemoteError, UnknownAsset, UnsupportedAsset
from rotkehlchen.exchanges.data_structures import AssetMovement, Trade, TradeType
from rotkehlchen.exchanges.kucoin import Kucoin, KucoinCase, SkipReason
from rotkehlchen.fval import FVal
from rotkehlchen.tests.utils.mock import MockResponse
from rotkehlchen.typing import (
    AssetAmount,
    AssetMovementCategory,
    Fee,
    Location,
    Price,
    Timestamp,
    TradePair,
)
from rotkehlchen.utils.serialization import rlk_jsonloads_dict


def test_name():
    exchange = Kucoin(
        api_key='a',
        secret=b'a',
        database=object(),
        msg_aggregator=object(),
        passphrase='a',
    )
    assert exchange.name == str(Location.KUCOIN)


def test_kucoin_exchange_assets_are_known(mock_kucoin):
    request_url = f'{mock_kucoin.base_uri}/api/v1/currencies'
    try:
        response = requests.get(request_url)
    except requests.exceptions.RequestException as e:
        raise RemoteError(
            f'Kucoin get request at {request_url} connection error: {str(e)}.',
        ) from e

    if response.status_code != HTTPStatus.OK:
        raise RemoteError(
            f'Kucoin query responded with error status code: {response.status_code} '
            f'and text: {response.text}',
        )
    try:
        response_dict = rlk_jsonloads_dict(response.text)
    except JSONDecodeError as e:
        raise RemoteError(f'Kucoin returned invalid JSON response: {response.text}') from e

    # Extract the unique symbols from the exchange pairs
    unsupported_assets = set(UNSUPPORTED_KUCOIN_ASSETS)
    for entry in response_dict['data']:
        symbol = entry['currency']
        try:
            asset_from_kucoin(symbol)
        except UnsupportedAsset:
            assert symbol in unsupported_assets
        except UnknownAsset as e:
            test_warnings.warn(UserWarning(
                f'Found unknown asset {e.asset_name} in kucoin. '
                f'Support for it has to be added',
            ))


def test_api_query_retries_request(mock_kucoin):

    def get_response():
        results = [
            """{"code":400007,"msg":"unknown error"}""",
            """{"code":400007,"msg":"unknown error"}""",
        ]
        for result_ in results:
            yield result_

    def mock_api_query_response(url):  # pylint: disable=unused-argument
        return MockResponse(HTTPStatus.TOO_MANY_REQUESTS, next(get_response))

    get_response = get_response()
    api_request_retry_times_patch = patch(
        target='rotkehlchen.exchanges.kucoin.API_REQUEST_RETRY_TIMES',
        new=1,
    )
    api_request_retry_after_seconds_patch = patch(
        target='rotkehlchen.exchanges.kucoin.API_REQUEST_RETRIES_AFTER_SECONDS',
        new=0,
    )
    api_query_patch = patch.object(
        target=mock_kucoin.session,
        attribute='get',
        side_effect=mock_api_query_response,
    )
    with ExitStack() as stack:
        stack.enter_context(api_request_retry_times_patch)
        stack.enter_context(api_request_retry_after_seconds_patch)
        stack.enter_context(api_query_patch)
        result = mock_kucoin._api_query(
            options={
                'currentPage': 1,
                'pageSize': 500,
                'tradeType': 'TRADE',
            },
            case=KucoinCase.TRADES,
        )

    assert result.status_code == HTTPStatus.TOO_MANY_REQUESTS
    errors = mock_kucoin.msg_aggregator.consume_errors()
    assert len(errors) == 1
    expected_error = (
        'Got remote error while querying kucoin trades: Kucoin trades request '
        'failed after retrying 1 times.'
    )
    assert errors[0] == expected_error


@pytest.mark.parametrize('should_mock_current_price_queries', [True])
def test_deserialize_accounts_balances(mock_kucoin, inquirer):  # pylint: disable=unused-argument
    accounts_data = [
        {
            'id': '601ac6f7d48f8000063ab2da',
            'currency': 'UNEXISTINGSYMBOL',
            'type': 'main',
            'balance': '999',
            'available': '999',
            'holds': '0',
        },
        {
            'id': '601ac6f7d48f8000063ab2db',
            'currency': 'BCHSV',
            'type': 'main',
            'balance': '1',
            'available': '1',
            'holds': '0',
        },
        {
            'id': '601ac6f7d48f8000063ab2de',
            'currency': 'BTC',
            'type': 'main',
            'balance': '2.52',
            'available': '2.52',
            'holds': '0',
        },
        {
            'id': '601ac6f7d48f8000063ab2e7',
            'currency': 'ETH',
            'type': 'main',
            'balance': '47.33',
            'available': '47.33',
            'holds': '0',
        },
        {
            'id': '601ac6f7d48f8000063ab2e1',
            'currency': 'USDT',
            'type': 'main',
            'balance': '34500',
            'available': '34500',
            'holds': '0',
        },
        {
            'id': '60228f81d48f8000060cec67',
            'currency': 'USDT',
            'type': 'margin',
            'balance': '10000',
            'available': '10000',
            'holds': '0',
        },
        {
            'id': '601acdb7d48f8000063c6d4a',
            'currency': 'BTC',
            'type': 'trade',
            'balance': '0.09018067',
            'available': '0.09018067',
            'holds': '0',
        },
        {
            'id': '601acdc5d48f8000063c70b3',
            'currency': 'USDT',
            'type': 'trade',
            'balance': '597.26244755',
            'available': '597.26244755',
            'holds': '0',
        },
        {
            'id': '601da9fad48f8000063960cc',
            'currency': 'KCS',
            'type': 'trade',
            'balance': '0.2',
            'available': '0.2',
            'holds': '0',
        },
        {
            'id': '601da9ddd48f80000639553f',
            'currency': 'ETH',
            'type': 'trade',
            'balance': '0.10934995',
            'available': '0.10934995',
            'holds': '0',
        },
    ]
    assets_balance = mock_kucoin._deserialize_accounts_balances({'data': accounts_data})
    assert assets_balance == {
        Asset('BTC'): Balance(
            amount=FVal('2.61018067'),
            usd_value=FVal('3.915271005'),
        ),
        Asset('ETH'): Balance(
            amount=FVal('47.43934995'),
            usd_value=FVal('71.159024925'),
        ),
        Asset('KCS'): Balance(
            amount=FVal('0.2'),
            usd_value=FVal('0.30'),
        ),
        Asset('USDT'): Balance(
            amount=FVal('45097.26244755'),
            usd_value=FVal('67645.893671325'),
        ),
        Asset('BSV'): Balance(
            amount=FVal('1'),
            usd_value=FVal('1.5'),
        ),
    }


def test_deserialize_trade_buy(mock_kucoin):
    raw_result = {
        'symbol': 'KCS-USDT',
        'tradeId': '601da9faf1297d0007efd712',
        'orderId': '601da9fa0c92050006bd83be',
        'counterOrderId': '601bad620c9205000642300f',
        'side': 'buy',
        'liquidity': 'taker',
        'forceTaker': True,
        'price': 1000,
        'size': '0.2',
        'funds': 200,
        'fee': '0.14',
        'feeRate': '0.0007',
        'feeCurrency': 'USDT',
        'stop': '',
        'tradeType': 'TRADE',
        'type': 'market',
        'createdAt': 1612556794259,
    }
    expected_trade = Trade(
        timestamp=Timestamp(1612556794),
        location=Location.KUCOIN,
        pair=TradePair('KCS_USDT'),
        trade_type=TradeType.BUY,
        amount=AssetAmount(FVal('0.2')),
        rate=Price(FVal('1000')),
        fee=Fee(FVal('0.14')),
        fee_currency=Asset('USDT'),
        link='601da9faf1297d0007efd712',
        notes='',
    )
    trade, reason = mock_kucoin._deserialize_trade(
        raw_result=raw_result,
        start_ts=Timestamp(0),
        end_ts=Timestamp(1612556794),
    )
    assert trade == expected_trade
    assert reason is None


def test_deserialize_trade_sell(mock_kucoin):
    raw_result = {
        'symbol': 'BCHSV-USDT',
        'tradeId': '601da995e0ee8b00063a075c',
        'orderId': '601da9950c92050006bd45c5',
        'counterOrderId': '601da9950c92050006bd457d',
        'side': 'sell',
        'liquidity': 'taker',
        'forceTaker': True,
        'price': '37624.4',
        'size': '0.0013',
        'funds': '48.91172',
        'fee': '0.034238204',
        'feeRate': '0.0007',
        'feeCurrency': 'USDT',
        'stop': '',
        'tradeType': 'TRADE',
        'type': 'market',
        'createdAt': 1612556794259,
    }
    expected_trade = Trade(
        timestamp=Timestamp(1612556794),
        location=Location.KUCOIN,
        pair=TradePair('BSV_USDT'),
        trade_type=TradeType.SELL,
        amount=AssetAmount(FVal('0.0013')),
        rate=Price(FVal('37624.4')),
        fee=Fee(FVal('0.034238204')),
        fee_currency=Asset('USDT'),
        link='601da995e0ee8b00063a075c',
        notes='',
    )
    trade, reason = mock_kucoin._deserialize_trade(
        raw_result=raw_result,
        start_ts=Timestamp(0),
        end_ts=Timestamp(1612556794),
    )
    assert trade == expected_trade
    assert reason is None


@pytest.mark.parametrize('start_ts, end_ts, skip_reason', [
    (0, 1612556793, SkipReason.AFTER_TIMESTAMP_RANGE),
    (1612556795, 1612556800, SkipReason.BEFORE_TIMESTAMP_RANGE),
])
def test_deserialize_trade_skipped(mock_kucoin, start_ts, end_ts, skip_reason):
    raw_result = {
        'symbol': 'KCS-USDT',
        'tradeId': '601da9faf1297d0007efd712',
        'orderId': '601da9fa0c92050006bd83be',
        'counterOrderId': '601bad620c9205000642300f',
        'side': 'buy',
        'liquidity': 'taker',
        'forceTaker': True,
        'price': 1000,
        'size': '0.2',
        'funds': 200,
        'fee': '0.14',
        'feeRate': '0.0007',
        'feeCurrency': 'USDT',
        'stop': '',
        'tradeType': 'TRADE',
        'type': 'market',
        'createdAt': 1612556794259,
    }
    trade, reason = mock_kucoin._deserialize_trade(
        raw_result=raw_result,
        start_ts=Timestamp(start_ts),
        end_ts=Timestamp(end_ts),
    )
    assert trade is None
    assert reason == skip_reason


def test_deserialize_asset_movement_deposit(mock_kucoin):
    raw_result = {
        'address': '0x5bedb060b8eb8d823e2414d82acce78d38be7fe9',
        'memo': '',
        'currency': 'ETH',
        'amount': 1,
        'fee': 0.01,
        'walletTxId': '3e2414d82acce78d38be7fe9',
        'isInner': False,
        'status': 'SUCCESS',
        'remark': 'test',
        'createdAt': 1612556794259,
        'updatedAt': 1612556795000,
    }
    expected_asset_movement = AssetMovement(
        timestamp=Timestamp(1612556794),
        location=Location.KUCOIN,
        category=AssetMovementCategory.DEPOSIT,
        address='0x5bedb060b8eb8d823e2414d82acce78d38be7fe9',
        transaction_id='3e2414d82acce78d38be7fe9',
        asset=Asset('ETH'),
        amount=AssetAmount(FVal('1')),
        fee_asset=Asset('ETH'),
        fee=Fee(FVal('0.01')),
        link='',
    )
    asset_movement, reason = mock_kucoin._deserialize_asset_movement(
        raw_result=raw_result,
        case=KucoinCase.DEPOSITS,
        start_ts=Timestamp(0),
        end_ts=Timestamp(1612556794),
    )
    assert asset_movement == expected_asset_movement
    assert reason is None


def test_deserialize_asset_movement_withdrawal(mock_kucoin):
    raw_result = {
        'id': '5c2dc64e03aa675aa263f1ac',
        'address': '0x5bedb060b8eb8d823e2414d82acce78d38be7fe9',
        'memo': '',
        'currency': 'ETH',
        'amount': 1,
        'fee': 0.01,
        'walletTxId': '3e2414d82acce78d38be7fe9',
        'isInner': False,
        'status': 'SUCCESS',
        'remark': 'test',
        'createdAt': 1612556794259,
        'updatedAt': 1612556795000,
    }
    expected_asset_movement = AssetMovement(
        timestamp=Timestamp(1612556794),
        location=Location.KUCOIN,
        category=AssetMovementCategory.WITHDRAWAL,
        address='0x5bedb060b8eb8d823e2414d82acce78d38be7fe9',
        transaction_id='3e2414d82acce78d38be7fe9',
        asset=Asset('ETH'),
        amount=AssetAmount(FVal('1')),
        fee_asset=Asset('ETH'),
        fee=Fee(FVal('0.01')),
        link='5c2dc64e03aa675aa263f1ac',
    )
    asset_movement, reason = mock_kucoin._deserialize_asset_movement(
        raw_result=raw_result,
        case=KucoinCase.WITHDRAWALS,
        start_ts=Timestamp(0),
        end_ts=Timestamp(1612556794),
    )
    assert asset_movement == expected_asset_movement
    assert reason is None


@pytest.mark.parametrize('start_ts, end_ts, is_inner, skip_reason', [
    (0, 1612556793, False, SkipReason.AFTER_TIMESTAMP_RANGE),
    (1612556795, 1612556800, False, SkipReason.BEFORE_TIMESTAMP_RANGE),
    (1612556750, 1612556800, True, SkipReason.INNER_MOVEMENT),
])
def test_deserialize_asset_movement_skipped(mock_kucoin, start_ts, end_ts, is_inner, skip_reason):
    raw_result = {
        'id': '5c2dc64e03aa675aa263f1ac',
        'address': '0x5bedb060b8eb8d823e2414d82acce78d38be7fe9',
        'memo': '',
        'currency': 'ETH',
        'amount': 1,
        'fee': 0.01,
        'walletTxId': '3e2414d82acce78d38be7fe9',
        'isInner': is_inner,
        'status': 'SUCCESS',
        'remark': 'test',
        'createdAt': 1612556794259,
        'updatedAt': 1612556795000,
    }
    asset_movement, reason = mock_kucoin._deserialize_asset_movement(
        raw_result=raw_result,
        case=KucoinCase.WITHDRAWALS,
        start_ts=Timestamp(start_ts),
        end_ts=Timestamp(end_ts),
    )
    assert asset_movement is None
    assert reason == skip_reason


@pytest.mark.parametrize('should_mock_current_price_queries', [True])
def test_query_balances_sandbox(sandbox_kuckoin, inquirer):  # pylint: disable=unused-argument
    assets_balance, msg = sandbox_kuckoin.query_balances()
    assert assets_balance == {
        Asset('BTC'): Balance(
            amount=FVal('2.61018067'),
            usd_value=FVal('3.915271005'),
        ),
        Asset('ETH'): Balance(
            amount=FVal('47.43934995'),
            usd_value=FVal('71.159024925'),
        ),
        Asset('KCS'): Balance(
            amount=FVal('0.2'),
            usd_value=FVal('0.30'),
        ),
        Asset('USDT'): Balance(
            amount=FVal('45097.26244755'),
            usd_value=FVal('67645.893671325'),
        ),
    }
    assert msg == ''


@pytest.mark.parametrize('should_mock_current_price_queries', [True])
def test_query_trades_sandbox(sandbox_kuckoin, inquirer):  # pylint: disable=unused-argument
    """The sandbox account has 6 trades. Below a list of the trades and their
    timestamps in ascending mode.
    - trade 1: 1612556651 -> skipped
    - trade 2: 1612556693
    - trade 3: 1612556765
    - trade 4: 1612556765
    - trade 5: 1612556765
    - trade 6: 1612556794 -> skipped

    By requesting trades from 1612556693 to 1612556765, the first and last trade
    should be skipped.
    """
    expected_trades = [
        Trade(
            timestamp=Timestamp(1612556765),
            location=Location.KUCOIN,
            pair=TradePair('ETH_BTC'),
            trade_type=TradeType.BUY,
            amount=AssetAmount(FVal('0.02934995')),
            rate=Price(FVal('0.046058')),
            fee=Fee(FVal('9.4625999797E-7')),
            fee_currency=Asset('BTC'),
            link='601da9ddf73c300006194ec6',
            notes='',
        ),
        Trade(
            timestamp=Timestamp(1612556765),
            location=Location.KUCOIN,
            pair=TradePair('ETH_BTC'),
            trade_type=TradeType.BUY,
            amount=AssetAmount(FVal('0.02')),
            rate=Price(FVal('0.04561')),
            fee=Fee(FVal('6.3854E-7')),
            fee_currency=Asset('BTC'),
            link='601da9ddf73c300006194ec5',
            notes='',
        ),
        Trade(
            timestamp=Timestamp(1612556765),
            location=Location.KUCOIN,
            pair=TradePair('ETH_BTC'),
            trade_type=TradeType.BUY,
            amount=AssetAmount(FVal('0.06')),
            rate=Price(FVal('0.0456')),
            fee=Fee(FVal('0.0000019152')),
            fee_currency=Asset('BTC'),
            link='601da9ddf73c300006194ec4',
            notes='',
        ),
        Trade(
            timestamp=Timestamp(1612556693),
            location=Location.KUCOIN,
            pair=TradePair('BTC_USDT'),
            trade_type=TradeType.SELL,
            amount=AssetAmount(FVal('0.0013')),
            rate=Price(FVal('37624.4')),
            fee=Fee(FVal('0.034238204')),
            fee_currency=Asset('USDT'),
            link='601da995e0ee8b00063a075c',
            notes='',
        ),
    ]
    trades = sandbox_kuckoin.query_online_trade_history(
        start_ts=Timestamp(1612556693),
        end_ts=Timestamp(1612556765),
    )
    assert trades == expected_trades


@pytest.mark.parametrize('should_mock_current_price_queries', [True])
def test_query_asset_movements_sandbox(
        sandbox_kuckoin,
        inquirer,  # pylint: disable=unused-argument
):
    """Unfortunately the sandbox environment does not support deposits and
    withdrawals, therefore they must be mocked.

    The sandbox account has 6 movements. Below a list of the movements and their
    timestamps in ascending mode.
    - movement 1 - deposit: 1612556651 -> skipped
    - movement 2 - deposit: 1612556693
    - movement 3 - withdraw: 1612556765 -> skipped, inner withdraw
    - movement 4 - deposit: 1612556765 -> skipped, inner deposit
    - movement 5 - withdraw: 1612556765
    - movement 6 - withdraw: 1612556794 -> skipped

    By requesting trades from 1612556693 to 1612556765, the first and last
    movement should be skipped, but also the two inner movements.
    """
    deposits_response = (
        """
        {
            "code":"200000",
            "data":{
                "currentPage":1,
                "pageSize":500,
                "totalNum":3,
                "totalPage":1,
                "items":[
                    {
                        "address":"1DrT5xUaJ3CBZPDeFR2qdjppM6dzs4rsMt",
                        "memo":"",
                        "currency":"BCHSV",
                        "amount":1,
                        "fee":0.1,
                        "walletTxId":"b893c3ece1b8d7cacb49a39ddd759cf407817f6902f566c443ba16614874ada6",
                        "isInner":true,
                        "status":"SUCCESS",
                        "remark":"movement 4 - deposit",
                        "createdAt":1612556765000,
                        "updatedAt":1612556780000
                    },
                    {
                        "address":"0x5f047b29041bcfdbf0e4478cdfa753a336ba6989",
                        "memo":"5c247c8a03aa677cea2a251d",
                        "amount":1,
                        "fee":0.0001,
                        "currency":"KCS",
                        "isInner":false,
                        "walletTxId":"5bbb57386d99522d9f954c5a",
                        "status":"SUCCESS",
                        "remark":"movement 2 - deposit",
                        "createdAt":1612556693000,
                        "updatedAt":1612556700000
                    },
                    {
                        "address":"0x5f047b29041bcfdbf0e4478cdfa753a336ba6989",
                        "memo":"5c247c8a03aa677cea2a251d",
                        "amount":1000,
                        "fee":0.01,
                        "currency":"LINK",
                        "isInner":false,
                        "walletTxId":"5bbb57386d99522d9f954c5b",
                        "status":"SUCCESS",
                        "remark":"movement 1 - deposit",
                        "createdAt":1612556651000,
                        "updatedAt":1612556658000
                    }
                ]
            }
        }
        """
    )
    withdrawals_response = (
        """
        {
            "code":"200000",
            "data":{
                "currentPage":1,
                "pageSize":500,
                "totalNum":3,
                "totalPage":1,
                "items":[
                    {
                        "id":"5c2dc64e03aa675aa263f1a6",
                        "address":"0x5bedb060b8eb8d823e2414d82acce78d38be7fe9",
                        "memo":"",
                        "currency":"ETH",
                        "amount":1,
                        "fee":0.01,
                        "walletTxId":"3e2414d82acce78d38be7fe0",
                        "isInner":false,
                        "status":"SUCCESS",
                        "remark":"movement 6 - withdraw",
                        "createdAt":1612556794000,
                        "updatedAt":1612556799000
                    },
                    {
                        "id":"5c2dc64e03aa675aa263f1a5",
                        "address":"1DrT5xUaJ3CBZPDeFR2qdjppM6dzs4rsMt",
                        "memo":"",
                        "currency":"BCHSV",
                        "amount":2.5,
                        "fee":0.25,
                        "walletTxId":"b893c3ece1b8d7cacb49a39ddd759cf407817f6902f566c443ba16614874ada5",
                        "isInner":false,
                        "status":"SUCCESS",
                        "remark":"movement 5 - withdraw",
                        "createdAt":1612556765000,
                        "updatedAt":1612556780000
                    },
                    {
                        "id":"5c2dc64e03aa675aa263f1a3",
                        "address":"0x5bedb060b8eb8d823e2414d82acce78d38be7fe9",
                        "memo":"",
                        "currency":"ETH",
                        "amount":1,
                        "fee":0.01,
                        "walletTxId":"3e2414d82acce78d38be7fe9",
                        "isInner":true,
                        "status":"SUCCESS",
                        "remark":"movement 3 - withdraw",
                        "createdAt":1612556765000,
                        "updatedAt":1612556765000
                    }
                ]
            }
        }
        """
    )
    expected_asset_movements = [
        AssetMovement(
            location=Location.KUCOIN,
            category=AssetMovementCategory.DEPOSIT,
            timestamp=Timestamp(1612556693),
            address='0x5f047b29041bcfdbf0e4478cdfa753a336ba6989',
            transaction_id='5bbb57386d99522d9f954c5a',
            asset=Asset('KCS'),
            amount=AssetAmount(FVal('1')),
            fee_asset=Asset('KCS'),
            fee=Fee(FVal('0.0001')),
            link='',
        ),
        AssetMovement(
            location=Location.KUCOIN,
            category=AssetMovementCategory.WITHDRAWAL,
            timestamp=Timestamp(1612556765),
            address='1DrT5xUaJ3CBZPDeFR2qdjppM6dzs4rsMt',
            transaction_id='b893c3ece1b8d7cacb49a39ddd759cf407817f6902f566c443ba16614874ada5',
            asset=Asset('BSV'),
            amount=AssetAmount(FVal('2.5')),
            fee_asset=Asset('BSV'),
            fee=Fee(FVal('0.25')),
            link='5c2dc64e03aa675aa263f1a5',
        ),
    ]

    def get_endpoints_response():
        results = [
            f'{deposits_response}',
            f'{withdrawals_response}',
        ]
        for result_ in results:
            yield result_

    def mock_api_query_response(case, options):  # pylint: disable=unused-argument
        return MockResponse(HTTPStatus.OK, next(get_response))

    get_response = get_endpoints_response()
    with patch.object(
        target=sandbox_kuckoin,
        attribute='_api_query',
        side_effect=mock_api_query_response,
    ):
        asset_movements = sandbox_kuckoin.query_online_deposits_withdrawals(
            start_ts=Timestamp(1612556693),
            end_ts=Timestamp(1612556765),
        )

    assert asset_movements == expected_asset_movements
