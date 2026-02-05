def arithmetic(a, b):
    total = a + b
    doubled = total * 2
    print('result is', doubled)
    return doubled


class Greeter:
    def greet(self, name: str) -> str:
        message = f'Hello, {name}!'
        print(message)
        return message
