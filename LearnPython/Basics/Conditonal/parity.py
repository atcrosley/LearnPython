# create a function to tell wether a number is even or odd

def main():
    x = int(input("What's x? "))
    if is_even(x):
        print("Even")
    else:
        print("Odd")


def is_even(n):
    if n % 2 == 0:
        return True
    else:
        return False
# another way to write on same line
# return True if n % 2 == 0 else False
# or you can write - return n % 2 == 0
# This works because we are returning a Boolean


main()
