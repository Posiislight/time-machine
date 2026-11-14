"""Test-only fixture: a session with logical state, observations and recorded external actions."""


def seeded_session(engine, uncertain=False):
    resources = {
        'agent': {'recovery': 'logical', 'state': {'goal': 'Buy headphones within budget', 'step': 'Compare basket'}},
        'browser': {'recovery': 'logical', 'state': {'url': 'demo-shop.local/cart', 'cart': ['Headphones'], 'total': '25000 NGN'}, 'adapter': 'simulated browser'},
        'android': {'recovery': 'unavailable', 'state': {'app': 'Shopping app', 'screen': 'Basket'}, 'adapter': 'recorded observation'},
        'network': {'recovery': 'unavailable', 'state': {'mode': 'country', 'countryCode': 'NG', 'session': 'sticky', 'observedIp': '192.0.2.10'}, 'adapter': 'recorded observation; previous IP cannot be reclaimed'}
    }
    sid = engine.create('Shopping recovery / simulated devices', resources)
    engine.checkpoint(sid, 'Before checkout')
    engine.effect(sid, 'checkout-order-001', 'payment', 'unknown' if uncertain else 'completed', 'NGN 25,000 headphones payment; order demo-001')
    engine.effect(sid, 'order-email-001', 'message', 'completed', 'Order confirmation email sent')
    resources['agent']['state']['step'] = 'Connection lost after checkout'
    resources['browser']['state']['url'] = 'demo-shop.local/connection-error'
    resources['network']['state']['observedIp'] = '192.0.2.20'
    engine.update(sid, resources)
    return sid
