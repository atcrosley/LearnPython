# make program to meow a number of times decided by user. must be positive number
def main():
    # make variable 'number' to store value from function get_number
    number = get_number()
    # call function meow, passing number as argument
    meow(number)


def get_number():
    # while loop runs while n is greater than 0
    while True:
        n = int(input("What's n?"))
        if n > 0:
            return n

# 'number' is changed to n. function meow loops for n times.


def meow(n):
    for _ in range(n):
        print("meow")


main()
