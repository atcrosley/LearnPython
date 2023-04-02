# implement a program that prompts the user for the name of a variable in camel case and outputs the corresponding name in snake case. Assume that the user's input be in camel case
def main():
    # ask user for name
    camel = input("Please enter name using camel case.")
    # print name
    print("camelCase: ", camel)
    # print name put through snakeconverter
    print("snake_case: ", snakeconverter(camel))


# converts camelcase to snake_case and returns to main
def snakeconverter(name):
    # loop through each letter to find uppercase
    for letter in name:
        if letter.isupper():
            # change uppercase letter to lower case and add underscore
            new = "_" + letter.lower()
            # put changed letter back in name
            return name.replace(letter, new)


main()
